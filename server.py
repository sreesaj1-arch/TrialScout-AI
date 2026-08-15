import contextlib
from math import asin, cos, radians, sin, sqrt
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount


# Legacy shared endpoint retained temporarily so the currently configured
# Agent Studio agents continue working while we migrate them one by one.
mcp = MCPServer("TrialScout MCP Server - Legacy Shared")

# Role-isolated MCP servers.
discovery_mcp = MCPServer("TrialScout Discovery MCP")
analysis_mcp = MCPServer("TrialScout Analysis MCP")
fhir_mcp = MCPServer("TrialScout FHIR Screening MCP")
matching_mcp = MCPServer("TrialScout Matching and Ranking MCP")


# Explicit transport security for local development and the deployed
# Google Cloud Run hostname.
CLOUD_RUN_HOST = "trialscout-mcp-790612148374.us-central1.run.app"

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        CLOUD_RUN_HOST,
        f"{CLOUD_RUN_HOST}:*",
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "[::1]",
        "[::1]:*",
    ],
    allowed_origins=[
        f"https://{CLOUD_RUN_HOST}",
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
    ],
)

CLINICAL_TRIALS_API = "https://clinicaltrials.gov/api/v2"
FEVIR_API = "https://api.fevir.net"
GOOGLE_GEOCODING_API = "https://maps.googleapis.com/maps/api/geocode/json"

FHIR_VERSION = "R6"
HL7_V2_MAPPING_FHIR_VERSION = "R4"
PATIENT_DATA_DIR = Path(__file__).resolve().parent / "data" / "synthea"

# ---------------------------------------------------------------------------
# Operational guardrails/configuration.
#
# These are named configuration values rather than hidden scoring logic.
# They can be overridden through environment variables when appropriate.
# ---------------------------------------------------------------------------
CLINICAL_TRIALS_TIMEOUT_SECONDS = float(
    os.getenv("TRIALSCOUT_CT_GOV_TIMEOUT_SECONDS", "30")
)
FEVIR_TIMEOUT_SECONDS = float(
    os.getenv("TRIALSCOUT_FEVIR_TIMEOUT_SECONDS", "90")
)
GEOCODING_TIMEOUT_SECONDS = float(
    os.getenv("TRIALSCOUT_GEOCODING_TIMEOUT_SECONDS", "15")
)

DISCOVERY_PAGE_SIZE = max(
    10,
    min(int(os.getenv("TRIALSCOUT_DISCOVERY_PAGE_SIZE", "100")), 1000),
)
DISCOVERY_MAX_PAGES = max(
    1,
    int(os.getenv("TRIALSCOUT_DISCOVERY_MAX_PAGES", "10")),
)

MAX_DISCOVERY_RESULTS = max(
    1,
    int(os.getenv("TRIALSCOUT_MAX_DISCOVERY_RESULTS", "10")),
)
MAX_SEARCH_RADIUS_MILES = max(
    1,
    int(os.getenv("TRIALSCOUT_MAX_RADIUS_MILES", "100")),
)
MIN_PARTICIPANT_AGE = 0
MAX_PARTICIPANT_AGE = max(
    1,
    int(os.getenv("TRIALSCOUT_MAX_PARTICIPANT_AGE", "120")),
)

MAX_TRIALS_PER_COMPARISON = max(
    2,
    int(os.getenv("TRIALSCOUT_MAX_COMPARE_TRIALS", "5")),
)
MAX_TRIALS_PER_RANKING = max(
    2,
    int(os.getenv("TRIALSCOUT_MAX_RANK_TRIALS", "5")),
)

MAX_LOCATION_RESULTS = max(
    1,
    int(os.getenv("TRIALSCOUT_MAX_LOCATION_RESULTS", "25")),
)
UNKNOWN_REQUIREMENT_PREVIEW_LIMIT = max(
    1,
    int(os.getenv("TRIALSCOUT_UNKNOWN_PREVIEW_LIMIT", "12")),
)
CONTACT_SITE_PREVIEW_LIMIT = max(
    1,
    int(os.getenv("TRIALSCOUT_CONTACT_SITE_PREVIEW_LIMIT", "8")),
)
HL7_V2_MESSAGE_MAX_CHARACTERS = max(
    1000,
    int(os.getenv("TRIALSCOUT_HL7_V2_MESSAGE_MAX_CHARACTERS", "100000")),
)
MAX_PATIENT_SUMMARY_ITEMS = max(
    1, int(os.getenv("TRIALSCOUT_MAX_PATIENT_SUMMARY_ITEMS", "50"))
)
MAX_DEMO_PATIENT_RESULTS = max(
    1, int(os.getenv("TRIALSCOUT_MAX_DEMO_PATIENT_RESULTS", "50"))
)
MAX_COMPARISON_LOCATIONS_PER_TRIAL = max(
    1, int(os.getenv("TRIALSCOUT_MAX_COMPARE_LOCATIONS", "10"))
)
COMPARISON_INTERVENTION_PREVIEW_LIMIT = max(
    1, int(os.getenv("TRIALSCOUT_COMPARE_INTERVENTION_PREVIEW_LIMIT", "10"))
)


def _format_location(location: dict[str, Any]) -> str:
    """Convert a ClinicalTrials.gov location object into readable text."""
    parts = [
        location.get("facility"),
        location.get("city"),
        location.get("state"),
        location.get("country"),
    ]

    return ", ".join(str(part) for part in parts if part)


def _condition_matches(
    requested_condition: str,
    study_conditions: list[str],
) -> bool:
    """
    Validate discovery relevance against the study's registered conditions.

    ClinicalTrials.gov search can return records whose free-text keywords are
    related to the query even when the registered condition list does not
    represent the requested disease. TrialScout therefore does not allow
    keywords alone to qualify a discovery result.

    This matcher intentionally uses only conditionsModule.conditions and does
    not guess clinical synonyms.
    """
    requested = "".join(
        character.casefold() if character.isalnum() else " "
        for character in requested_condition
    )
    requested = " ".join(requested.split())

    if not requested:
        return True

    normalized_conditions: list[str] = []

    for value in study_conditions:
        if not isinstance(value, str):
            continue

        normalized = "".join(
            character.casefold() if character.isalnum() else " "
            for character in value
        )
        normalized = " ".join(normalized.split())

        if normalized:
            normalized_conditions.append(normalized)

    if not normalized_conditions:
        return False

    # Direct phrase match handles simple requests such as "diabetes".
    if any(
        requested in value or value in requested
        for value in normalized_conditions
    ):
        return True

    # Conservative token matching handles wording/order differences such as
    # "Type 2 diabetes" versus "Diabetes Mellitus, Type 2".
    ignored_words = {
        "and",
        "or",
        "of",
        "the",
        "with",
        "disease",
        "disorder",
        "condition",
        "syndrome",
        "mellitus",
    }

    requested_tokens = {
        token
        for token in requested.split()
        if token not in ignored_words and len(token) > 1
    }

    if not requested_tokens:
        return False

    for value in normalized_conditions:
        value_tokens = {
            token
            for token in value.split()
            if token not in ignored_words and len(token) > 1
        }

        if requested_tokens.issubset(value_tokens):
            return True

    return False


def _normalize_phase_filter(value: str) -> tuple[str | None, str | None]:
    """Normalize a user-supplied trial phase to ClinicalTrials.gov values."""
    normalized = "".join(
        character.casefold() if character.isalnum() else " "
        for character in value
    )
    normalized = " ".join(normalized.split())

    if not normalized:
        return None, None

    aliases = {
        "early phase 1": "EARLY_PHASE1",
        "early phase1": "EARLY_PHASE1",
        "earlyphase1": "EARLY_PHASE1",
        "phase 0": "EARLY_PHASE1",
        "phase0": "EARLY_PHASE1",
        "0": "EARLY_PHASE1",
        "phase 1": "PHASE1",
        "phase1": "PHASE1",
        "1": "PHASE1",
        "phase 2": "PHASE2",
        "phase2": "PHASE2",
        "2": "PHASE2",
        "phase 3": "PHASE3",
        "phase3": "PHASE3",
        "3": "PHASE3",
        "phase 4": "PHASE4",
        "phase4": "PHASE4",
        "4": "PHASE4",
        "not applicable": "NA",
        "notapplicable": "NA",
        "n a": "NA",
        "na": "NA",
    }

    canonical = aliases.get(normalized)

    if canonical is None:
        return None, (
            "Unsupported trial phase. Use Early Phase 1, Phase 1, Phase 2, "
            "Phase 3, Phase 4, or Not Applicable."
        )

    return canonical, None


def _parse_age_years(value: str | None) -> float | None:
    """Convert a ClinicalTrials.gov age string into approximate years."""
    if not value:
        return None

    parts = value.split()

    if len(parts) < 2:
        return None

    try:
        number = float(parts[0])
    except ValueError:
        return None

    unit = parts[1].lower()

    if unit.startswith("year"):
        return number

    if unit.startswith("month"):
        return number / 12

    if unit.startswith("week"):
        return number / 52

    if unit.startswith("day"):
        return number / 365

    return None


def _haversine_distance_miles(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """
    Calculate straight-line geographic distance between two coordinates.

    The result is returned in miles.
    """
    earth_radius_miles = 3958.8

    lat_1 = radians(latitude_1)
    lon_1 = radians(longitude_1)
    lat_2 = radians(latitude_2)
    lon_2 = radians(longitude_2)

    delta_lat = lat_2 - lat_1
    delta_lon = lon_2 - lon_1

    haversine_value = (
        sin(delta_lat / 2) ** 2
        + cos(lat_1) * cos(lat_2) * sin(delta_lon / 2) ** 2
    )

    angular_distance = 2 * asin(sqrt(haversine_value))

    return earth_radius_miles * angular_distance


def _get_location_coordinates(
    location: dict[str, Any],
) -> tuple[float, float] | None:
    """Extract latitude and longitude from a trial location."""
    geo_point = location.get("geoPoint")

    if not isinstance(geo_point, dict):
        return None

    latitude = geo_point.get("lat")
    longitude = geo_point.get("lon")

    if not isinstance(latitude, (int, float)):
        return None

    if not isinstance(longitude, (int, float)):
        return None

    return float(latitude), float(longitude)


def _shorten_text(text: str | None, maximum_length: int = 1200) -> str:
    """Limit long eligibility text in search results."""
    if not text:
        return ""

    if len(text) <= maximum_length:
        return text

    return text[:maximum_length].rstrip() + "..."

def _fhir_codeable_text(value: Any) -> str | None:
    """Return readable text from a FHIR CodeableConcept-like object."""
    if isinstance(value, str):
        return value

    if not isinstance(value, dict):
        return None

    text = value.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    codings = value.get("coding", [])
    if isinstance(codings, list):
        for coding in codings:
            if not isinstance(coding, dict):
                continue

            display = coding.get("display")
            if isinstance(display, str) and display.strip():
                return display.strip()

            code = coding.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()

    return None


def _fhir_profiles(resource: dict[str, Any]) -> list[str]:
    """Return profile URLs declared on a FHIR resource."""
    meta = resource.get("meta", {})

    if not isinstance(meta, dict):
        return []

    profiles = meta.get("profile", [])

    if not isinstance(profiles, list):
        return []

    return [
        str(profile)
        for profile in profiles
        if isinstance(profile, str)
    ]


def _find_fhir_bundle(payload: Any, depth: int = 0) -> dict[str, Any] | None:
    """
    Locate a FHIR Bundle in a FEvIR API response.

    The converter may return the Bundle directly or wrap it inside another
    response object, so this helper searches a small number of nested levels.
    """
    if depth > 5:
        return None

    if isinstance(payload, dict):
        if payload.get("resourceType") == "Bundle":
            return payload

        preferred_keys = (
            "bundle",
            "fhirBundle",
            "fhir_bundle",
            "result",
            "data",
            "return",
            "response",
        )

        for key in preferred_keys:
            if key in payload:
                found = _find_fhir_bundle(payload.get(key), depth + 1)
                if found is not None:
                    return found

        for value in payload.values():
            if isinstance(value, (dict, list)):
                found = _find_fhir_bundle(value, depth + 1)
                if found is not None:
                    return found

    elif isinstance(payload, list):
        for value in payload:
            found = _find_fhir_bundle(value, depth + 1)
            if found is not None:
                return found

    return None


def _flatten_fhir_resources(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Collect top-level and contained FHIR resources from a Bundle.

    ClinicalTrials.gov FHIR exports can place many supporting resources inside
    the primary ResearchStudy's contained array.
    """
    resources: list[dict[str, Any]] = []

    def visit(resource: Any) -> None:
        if not isinstance(resource, dict):
            return

        resource_type = resource.get("resourceType")

        if isinstance(resource_type, str):
            resources.append(resource)

        contained = resource.get("contained", [])
        if isinstance(contained, list):
            for child in contained:
                visit(child)

    for entry in bundle.get("entry", []):
        if not isinstance(entry, dict):
            continue
        visit(entry.get("resource"))

    return resources


def _count_fhir_resources(
    resources: list[dict[str, Any]],
) -> dict[str, int]:
    """Count FHIR resources by resourceType."""
    counts: dict[str, int] = {}

    for resource in resources:
        resource_type = resource.get("resourceType")

        if not isinstance(resource_type, str):
            continue

        counts[resource_type] = counts.get(resource_type, 0) + 1

    return dict(sorted(counts.items()))


def _find_main_fhir_research_study(
    resources: list[dict[str, Any]],
    nct_id: str,
) -> dict[str, Any] | None:
    """Identify the main study-registry ResearchStudy resource."""
    research_studies = [
        resource
        for resource in resources
        if resource.get("resourceType") == "ResearchStudy"
    ]

    for resource in research_studies:
        profiles = _fhir_profiles(resource)
        if any("study-registry-record" in profile for profile in profiles):
            return resource

    normalized = nct_id.casefold()

    for resource in research_studies:
        resource_id = str(resource.get("id", "")).casefold()
        name = str(resource.get("name", "")).casefold()

        if normalized in resource_id and "fhir transform" in resource_id:
            return resource

        if normalized in name and "fhir_transform" in name:
            return resource

    for resource in research_studies:
        profiles = _fhir_profiles(resource)
        if not any("research-study-site" in profile for profile in profiles):
            return resource

    return research_studies[0] if research_studies else None


def _extract_fhir_identifier(
    resource: dict[str, Any],
    system_contains: str,
) -> str | None:
    """Extract an identifier whose system contains a requested value."""
    needle = system_contains.casefold()

    for identifier in resource.get("identifier", []):
        if not isinstance(identifier, dict):
            continue

        system = str(identifier.get("system", "")).casefold()
        value = identifier.get("value")

        if needle in system and isinstance(value, str):
            return value

    return None


def _extract_fhir_official_title(
    research_study: dict[str, Any],
) -> str | None:
    """Extract the official title from ResearchStudy.label when available."""
    for label in research_study.get("label", []):
        if not isinstance(label, dict):
            continue

        label_type = label.get("type", {})
        codings = label_type.get("coding", []) if isinstance(label_type, dict) else []

        is_official = False
        for coding in codings:
            if not isinstance(coding, dict):
                continue
            if str(coding.get("code", "")).casefold() == "official":
                is_official = True
                break

        if is_official:
            value = label.get("value")
            if isinstance(value, str):
                return value

    return None


def _extract_fhir_interventions(
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract intervention EvidenceVariable resources."""
    interventions: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "EvidenceVariable":
            continue

        classifier_texts: list[str] = []
        for classifier in resource.get("classifier", []):
            if not isinstance(classifier, dict):
                continue
            text = classifier.get("text")
            if isinstance(text, str):
                classifier_texts.append(text)

        intervention_classifier = next(
            (
                text
                for text in classifier_texts
                if text.casefold().startswith("intervention type:")
            ),
            None,
        )

        if intervention_classifier is None:
            continue

        intervention_type = intervention_classifier.split(":", 1)[-1].strip()

        alternative_names = []
        for note in resource.get("note", []):
            if isinstance(note, dict):
                text = note.get("text")
                if isinstance(text, str) and text.strip():
                    alternative_names.append(text.strip())

        interventions.append(
            {
                "id": resource.get("id"),
                "type": intervention_type or None,
                "name": resource.get("title") or resource.get("name"),
                "description": resource.get("description"),
                "notes": alternative_names,
            }
        )

    return interventions


def _extract_fhir_comparison_groups(
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract trial treatment/comparator Group resources."""
    groups: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "Group":
            continue

        resource_id = str(resource.get("id", ""))
        title = str(resource.get("title", ""))

        if (
            "comparison-group" not in resource_id.casefold()
            and "comparison group" not in title.casefold()
        ):
            continue

        exposures: list[str] = []

        for characteristic in resource.get("characteristic", []):
            if not isinstance(characteristic, dict):
                continue

            value_reference = characteristic.get("valueReference")
            if not isinstance(value_reference, dict):
                continue

            display = value_reference.get("display")
            if isinstance(display, str) and display.strip():
                exposures.append(display.strip())

        groups.append(
            {
                "id": resource.get("id"),
                "title": resource.get("title"),
                "group_type": _fhir_codeable_text(resource.get("code")),
                "combination_method": resource.get("combinationMethod"),
                "exposures": exposures,
            }
        )

    return groups


def _extract_fhir_contacts(
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract central contact Practitioner resources."""
    contacts: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "Practitioner":
            continue

        resource_id = str(resource.get("id", ""))
        if "centralcontact" not in resource_id.casefold():
            continue

        name = None
        names = resource.get("name", [])
        if isinstance(names, list):
            for item in names:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    name = item.get("text")
                    break

        telecom: dict[str, str] = {}
        for item in resource.get("telecom", []):
            if not isinstance(item, dict):
                continue
            system = item.get("system")
            value = item.get("value")
            if isinstance(system, str) and isinstance(value, str):
                telecom[system] = value

        contacts.append(
            {
                "name": name,
                "phone": telecom.get("phone"),
                "email": telecom.get("email"),
            }
        )

    return contacts


def _extract_fhir_site_status_map(
    resources: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Map contained Location IDs to their site recruitment statuses."""
    status_map: dict[str, list[str]] = {}

    for resource in resources:
        if resource.get("resourceType") != "ResearchStudy":
            continue

        profiles = _fhir_profiles(resource)
        if not any("research-study-site" in profile for profile in profiles):
            continue

        site_refs = resource.get("site", [])
        if not isinstance(site_refs, list):
            continue

        statuses: list[str] = []
        for progress in resource.get("progressStatus", []):
            if not isinstance(progress, dict):
                continue
            status_text = _fhir_codeable_text(progress.get("state"))
            if status_text and status_text not in statuses:
                statuses.append(status_text)

        for site_ref in site_refs:
            if not isinstance(site_ref, dict):
                continue

            reference = site_ref.get("reference")
            if not isinstance(reference, str):
                continue

            location_id = reference.lstrip("#")
            if location_id:
                status_map[location_id] = statuses

    return status_map


def _extract_fhir_locations(
    resources: list[dict[str, Any]],
    location_filter: str,
    maximum_locations: int,
) -> list[dict[str, Any]]:
    """Extract and optionally filter FHIR Location resources."""
    requested_parts = [
        part.strip().casefold()
        for part in location_filter.split(",")
        if part.strip()
    ]

    site_status_map = _extract_fhir_site_status_map(resources)
    locations: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "Location":
            continue

        address = resource.get("address", {})
        if not isinstance(address, dict):
            address = {}

        searchable_location = " ".join(
            str(value)
            for value in [
                resource.get("name"),
                address.get("city"),
                address.get("state"),
                address.get("postalCode"),
                address.get("country"),
            ]
            if value
        ).casefold()

        if requested_parts and not all(
            part in searchable_location
            for part in requested_parts
        ):
            continue

        position = resource.get("position", {})
        if not isinstance(position, dict):
            position = {}

        contacts: list[dict[str, Any]] = []
        for contact in resource.get("contact", []):
            if not isinstance(contact, dict):
                continue

            contact_name = None
            names = contact.get("name", [])
            if isinstance(names, list):
                for name_item in names:
                    if (
                        isinstance(name_item, dict)
                        and isinstance(name_item.get("text"), str)
                    ):
                        contact_name = name_item.get("text")
                        break

            telecom: dict[str, str] = {}
            for item in contact.get("telecom", []):
                if not isinstance(item, dict):
                    continue
                system = item.get("system")
                value = item.get("value")
                if isinstance(system, str) and isinstance(value, str):
                    telecom[system] = value

            contacts.append(
                {
                    "name": contact_name,
                    "phone": telecom.get("phone"),
                    "email": telecom.get("email"),
                }
            )

        locations.append(
            {
                "id": resource.get("id"),
                "facility": resource.get("name"),
                "city": address.get("city"),
                "state": address.get("state"),
                "postal_code": address.get("postalCode"),
                "country": address.get("country"),
                "latitude": position.get("latitude"),
                "longitude": position.get("longitude"),
                "site_statuses": site_status_map.get(
                    str(resource.get("id", "")),
                    [],
                ),
                "contacts": contacts,
            }
        )

        if len(locations) >= maximum_locations:
            break

    return locations


def _extract_fhir_objectives(
    research_study: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract primary and secondary objectives/outcome measures."""
    objectives: list[dict[str, Any]] = []

    for objective in research_study.get("objective", []):
        if not isinstance(objective, dict):
            continue

        objective_type = _fhir_codeable_text(objective.get("type"))
        measures: list[dict[str, Any]] = []

        for measure in objective.get("outcomeMeasure", []):
            if not isinstance(measure, dict):
                continue

            endpoint = measure.get("endpoint", {})
            endpoint_display = None
            endpoint_type = None

            if isinstance(endpoint, dict):
                endpoint_display = endpoint.get("display")
                endpoint_type = endpoint.get("type")

            measures.append(
                {
                    "name": measure.get("name"),
                    "type": _fhir_codeable_text(measure.get("type")),
                    "endpoint_type": endpoint_type,
                    "endpoint_display": endpoint_display,
                }
            )

        objectives.append(
            {
                "type": objective_type,
                "outcome_measures": measures,
            }
        )

    return objectives



def _extract_fhir_eligibility_group(
    resources: list[dict[str, Any]],
    nct_id: str,
) -> dict[str, Any] | None:
    """
    Extract the complete structured eligibility Group when one is present.

    No artificial characteristic-count cutoff is applied here. Presentation
    limits are handled later so total unresolved counts remain truthful.
    """
    normalized = nct_id.casefold()
    candidates: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "Group":
            continue

        resource_id = str(resource.get("id", "")).casefold()
        title = str(resource.get("title", "")).casefold()

        identifier_values = []
        for identifier in resource.get("identifier", []):
            if isinstance(identifier, dict):
                value = identifier.get("value")
                if isinstance(value, str):
                    identifier_values.append(value.casefold())

        if (
            "eligibility" in resource_id
            or "eligibility" in title
            or any("eligibility" in value for value in identifier_values)
        ):
            candidates.append(resource)

    if not candidates:
        return None

    group = next(
        (
            candidate
            for candidate in candidates
            if normalized in str(candidate.get("id", "")).casefold()
            or normalized in str(candidate.get("title", "")).casefold()
        ),
        candidates[0],
    )

    characteristics: list[dict[str, Any]] = []

    raw_characteristics = group.get("characteristic", [])
    if not isinstance(raw_characteristics, list):
        raw_characteristics = []

    for characteristic in raw_characteristics:
        if not isinstance(characteristic, dict):
            continue

        value: Any = None
        value_type: str | None = None

        for key, candidate_value in characteristic.items():
            if key.startswith("value"):
                value_type = key

                if isinstance(candidate_value, dict):
                    value = (
                        _fhir_codeable_text(candidate_value)
                        or candidate_value.get("display")
                        or candidate_value.get("value")
                        or candidate_value
                    )
                else:
                    value = candidate_value
                break

        characteristics.append(
            {
                "criterion": _fhir_codeable_text(
                    characteristic.get("code")
                ),
                "exclude": characteristic.get("exclude"),
                "value_type": value_type,
                "value": value,
            }
        )

    return {
        "id": group.get("id"),
        "title": group.get("title"),
        "membership": group.get("membership"),
        "characteristic_count": len(characteristics),
        "characteristics": characteristics,
    }



def _fhir_status_code(value: Any) -> str | None:
    """Extract the first code from a FHIR CodeableConcept."""
    if not isinstance(value, dict):
        return None

    codings = value.get("coding", [])
    if not isinstance(codings, list):
        return None

    for coding in codings:
        if not isinstance(coding, dict):
            continue

        code = coding.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip().casefold()

    return None


def _calculate_age(birth_date_text: str | None) -> int | None:
    """Calculate age in completed years from a FHIR birthDate."""
    if not birth_date_text:
        return None

    try:
        birth_date = date.fromisoformat(birth_date_text)
    except ValueError:
        return None

    today = date.today()
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


def _fhir_patient_name(patient: dict[str, Any]) -> str | None:
    """Extract a readable patient name from a FHIR Patient resource."""
    names = patient.get("name", [])
    if not isinstance(names, list):
        return None

    preferred = None

    for name in names:
        if not isinstance(name, dict):
            continue

        if name.get("use") == "official":
            preferred = name
            break

        if preferred is None:
            preferred = name

    if not isinstance(preferred, dict):
        return None

    text = preferred.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    given = preferred.get("given", [])
    if not isinstance(given, list):
        given = []

    parts = [
        *(str(value) for value in given if value),
        str(preferred.get("family")) if preferred.get("family") else "",
    ]

    readable = " ".join(part for part in parts if part).strip()
    return readable or None


def _fhir_patient_location(patient: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a simple patient location summary."""
    addresses = patient.get("address", [])
    if not isinstance(addresses, list) or not addresses:
        return None

    address = next(
        (item for item in addresses if isinstance(item, dict)),
        None,
    )

    if not isinstance(address, dict):
        return None

    return {
        "city": address.get("city"),
        "state": address.get("state"),
        "postal_code": address.get("postalCode"),
        "country": address.get("country"),
    }


def _fhir_medication_name(resource: dict[str, Any]) -> str | None:
    """Extract a readable medication name from MedicationRequest."""
    medication = resource.get("medicationCodeableConcept")
    medication_text = _fhir_codeable_text(medication)

    if medication_text:
        return medication_text

    medication_reference = resource.get("medicationReference")
    if isinstance(medication_reference, dict):
        display = medication_reference.get("display")
        if isinstance(display, str) and display.strip():
            return display.strip()

    return None


def _fhir_observation_value(resource: dict[str, Any]) -> dict[str, Any] | None:
    """Extract one readable value from a FHIR Observation."""
    quantity = resource.get("valueQuantity")
    if isinstance(quantity, dict):
        return {
            "value": quantity.get("value"),
            "unit": quantity.get("unit") or quantity.get("code"),
            "value_type": "quantity",
        }

    value_string = resource.get("valueString")
    if isinstance(value_string, str):
        return {
            "value": value_string,
            "unit": None,
            "value_type": "string",
        }

    value_boolean = resource.get("valueBoolean")
    if isinstance(value_boolean, bool):
        return {
            "value": value_boolean,
            "unit": None,
            "value_type": "boolean",
        }

    value_integer = resource.get("valueInteger")
    if isinstance(value_integer, int):
        return {
            "value": value_integer,
            "unit": None,
            "value_type": "integer",
        }

    value_codeable = resource.get("valueCodeableConcept")
    value_codeable_text = _fhir_codeable_text(value_codeable)
    if value_codeable_text:
        return {
            "value": value_codeable_text,
            "unit": None,
            "value_type": "codeable_concept",
        }

    components = resource.get("component", [])
    if isinstance(components, list) and components:
        component_values: list[dict[str, Any]] = []

        for component in components:
            if not isinstance(component, dict):
                continue

            component_name = _fhir_codeable_text(component.get("code"))
            component_quantity = component.get("valueQuantity")

            if (
                component_name
                and isinstance(component_quantity, dict)
                and component_quantity.get("value") is not None
            ):
                component_values.append(
                    {
                        "name": component_name,
                        "value": component_quantity.get("value"),
                        "unit": (
                            component_quantity.get("unit")
                            or component_quantity.get("code")
                        ),
                    }
                )

        if component_values:
            return {
                "value": component_values,
                "unit": None,
                "value_type": "components",
            }

    return None


def _fhir_observation_date(resource: dict[str, Any]) -> str | None:
    """Return the best available date for a FHIR Observation."""
    for key in ("effectiveDateTime", "issued"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    effective_period = resource.get("effectivePeriod")
    if isinstance(effective_period, dict):
        end = effective_period.get("end")
        if isinstance(end, str) and end.strip():
            return end.strip()

        start = effective_period.get("start")
        if isinstance(start, str) and start.strip():
            return start.strip()

    return None


def _fhir_coding_summary(value: Any) -> dict[str, Any]:
    """Return text and the first coding for a CodeableConcept."""
    result = {
        "text": _fhir_codeable_text(value),
        "system": None,
        "code": None,
    }

    if not isinstance(value, dict):
        return result

    codings = value.get("coding", [])
    if not isinstance(codings, list):
        return result

    for coding in codings:
        if not isinstance(coding, dict):
            continue

        result["system"] = coding.get("system")
        result["code"] = coding.get("code")
        break

    return result


def _load_synthea_patient_bundle(
    patient_reference: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """
    Safely load one synthetic Synthea FHIR Bundle.

    Accepts either:
    - the exact JSON filename
    - a patient name such as "Lou"
    - a guessed filename such as "Lou.json" or "Lou_FHIR_R6.json"

    Returns:
        bundle, error, resolved_filename
    """
    requested = patient_reference.strip()

    if not requested:
        return None, "A patient name or filename is required.", None

    # Prevent arbitrary filesystem paths.
    if "/" in requested or "\\" in requested:
        return (
            None,
            "Provide only a patient name or filename, not a filesystem path.",
            None,
        )

    # ---------------------------------------------------------
    # 1. Exact filename match first
    # ---------------------------------------------------------
    exact_path = PATIENT_DATA_DIR / requested

    if exact_path.is_file():
        resolved_path = exact_path

    else:
        # -----------------------------------------------------
        # 2. Try resolving a human-readable / guessed name
        # -----------------------------------------------------
        reference_stem = Path(requested).stem.casefold()

        # Remove words an LLM may add to a patient filename.
        ignored_tokens = {
            "fhir",
            "r4",
            "r5",
            "r6",
            "patient",
            "bundle",
            "synthetic",
            "demo",
            "json",
        }

        normalized_reference = "".join(
            character if character.isalnum() else " "
            for character in reference_stem
        )

        query_tokens = [
            token
            for token in normalized_reference.split()
            if token and token not in ignored_tokens
        ]

        if not query_tokens:
            return (
                None,
                f"Unable to resolve patient reference '{requested}'.",
                None,
            )

        matches: list[Path] = []

        for candidate_path in PATIENT_DATA_DIR.glob("*.json"):
            try:
                with candidate_path.open(
                    "r",
                    encoding="utf-8",
                ) as handle:
                    candidate_bundle = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue

            if (
                not isinstance(candidate_bundle, dict)
                or candidate_bundle.get("resourceType") != "Bundle"
            ):
                continue

            patient_resource = None

            for entry in candidate_bundle.get("entry", []):
                if not isinstance(entry, dict):
                    continue

                resource = entry.get("resource")

                if (
                    isinstance(resource, dict)
                    and resource.get("resourceType") == "Patient"
                ):
                    patient_resource = resource
                    break

            patient_name = (
                _fhir_patient_name(patient_resource)
                if patient_resource
                else ""
            )

            searchable = " ".join(
                [
                    candidate_path.stem,
                    str(patient_name or ""),
                    str(
                        patient_resource.get("id", "")
                        if patient_resource
                        else ""
                    ),
                ]
            ).casefold()

            searchable = "".join(
                character if character.isalnum() else " "
                for character in searchable
            )

            # Every meaningful query token must appear in the patient data.
            if all(token in searchable for token in query_tokens):
                matches.append(candidate_path)

        if len(matches) == 0:
            return (
                None,
                (
                    f"No synthetic patient matched '{requested}'. "
                    "Use list_demo_patients to see available patients."
                ),
                None,
            )

        if len(matches) > 1:
            return (
                None,
                (
                    f"Multiple synthetic patients matched '{requested}'. "
                    "Use list_demo_patients to choose the intended patient."
                ),
                None,
            )

        resolved_path = matches[0]

    # ---------------------------------------------------------
    # 3. Load the resolved FHIR Bundle
    # ---------------------------------------------------------
    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError:
        return None, "The patient file is not valid JSON.", None
    except OSError as exc:
        return None, f"Unable to read the patient file: {exc}", None

    if not isinstance(payload, dict):
        return None, "The patient file must contain a JSON object.", None

    if payload.get("resourceType") != "Bundle":
        return None, "The patient file is not a FHIR Bundle.", None

    return payload, None, resolved_path.name

def _extract_patient_fhir_summary(
    bundle: dict[str, Any],
    maximum_conditions: int,
    maximum_medications: int,
    maximum_observations: int,
) -> dict[str, Any]:
    """Convert a large patient FHIR Bundle into a compact screening summary."""
    resources = _flatten_fhir_resources(bundle)
    resource_counts = _count_fhir_resources(resources)

    patients = [
        resource
        for resource in resources
        if resource.get("resourceType") == "Patient"
    ]

    if not patients:
        return {
            "success": False,
            "error": "The FHIR Bundle does not contain a Patient resource.",
            "resource_counts": resource_counts,
        }

    patient = patients[0]
    birth_date = patient.get("birthDate")

    active_conditions: list[dict[str, Any]] = []
    historical_conditions: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "Condition":
            continue

        code_summary = _fhir_coding_summary(resource.get("code"))
        condition_text = code_summary.get("text")

        if not condition_text:
            continue

        clinical_status = _fhir_status_code(
            resource.get("clinicalStatus")
        )

        condition_summary = {
            "name": condition_text,
            "clinical_status": clinical_status,
            "verification_status": _fhir_status_code(
                resource.get("verificationStatus")
            ),
            "system": code_summary.get("system"),
            "code": code_summary.get("code"),
            "onset": (
                resource.get("onsetDateTime")
                or resource.get("onsetPeriod")
            ),
            "abatement": (
                resource.get("abatementDateTime")
                or resource.get("abatementPeriod")
            ),
        }

        if clinical_status == "active":
            active_conditions.append(condition_summary)
        else:
            historical_conditions.append(condition_summary)

    active_medications: list[dict[str, Any]] = []
    historical_medications: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "MedicationRequest":
            continue

        medication_name = _fhir_medication_name(resource)
        if not medication_name:
            continue

        medication_status = str(resource.get("status", "")).casefold()

        medication_summary = {
            "name": medication_name,
            "status": medication_status or None,
            "intent": resource.get("intent"),
            "authored_on": resource.get("authoredOn"),
        }

        if medication_status == "active":
            active_medications.append(medication_summary)
        else:
            historical_medications.append(medication_summary)

    latest_observations_by_key: dict[str, dict[str, Any]] = {}

    for resource in resources:
        if resource.get("resourceType") != "Observation":
            continue

        status = str(resource.get("status", "")).casefold()
        if status and status not in {"final", "amended", "corrected"}:
            continue

        code_summary = _fhir_coding_summary(resource.get("code"))
        observation_name = code_summary.get("text")
        observation_value = _fhir_observation_value(resource)

        if not observation_name or observation_value is None:
            continue

        observation_date = _fhir_observation_date(resource)

        key = (
            str(code_summary.get("system") or "")
            + "|"
            + str(code_summary.get("code") or observation_name)
        )

        candidate = {
            "name": observation_name,
            "system": code_summary.get("system"),
            "code": code_summary.get("code"),
            "date": observation_date,
            **observation_value,
        }

        current = latest_observations_by_key.get(key)
        current_date = str(current.get("date") or "") if current else ""
        candidate_date = str(observation_date or "")

        if current is None or candidate_date >= current_date:
            latest_observations_by_key[key] = candidate

    latest_observations = sorted(
        latest_observations_by_key.values(),
        key=lambda item: str(item.get("date") or ""),
        reverse=True,
    )

    return {
        "success": True,
        "fhir_version": "R4 / US Core-style Synthea patient bundle",
        "bundle": {
            "resource_type": bundle.get("resourceType"),
            "bundle_type": bundle.get("type"),
            "total_resources_parsed": len(resources),
            "resource_counts": resource_counts,
        },
        "patient": {
            "fhir_resource_id": patient.get("id"),
            "profiles": _fhir_profiles(patient),
            "name": _fhir_patient_name(patient),
            "gender": patient.get("gender"),
            "birth_date": birth_date,
            "age_years": (
                _calculate_age(birth_date)
                if isinstance(birth_date, str)
                else None
            ),
            "location": _fhir_patient_location(patient),
        },
        "clinical_summary": {
            "active_condition_count": len(active_conditions),
            "active_conditions": active_conditions[:maximum_conditions],
            "historical_condition_count": len(historical_conditions),
            "active_medication_count": len(active_medications),
            "active_medications": active_medications[:maximum_medications],
            "historical_medication_count": len(historical_medications),
            "latest_observation_count_before_limit": len(
                latest_observations
            ),
            "latest_observations": latest_observations[
                :maximum_observations
            ],
        },
        "screening_note": (
            "This summary is extracted from synthetic Synthea FHIR data for "
            "research and software testing. It is not a real patient record "
            "and does not establish clinical-trial eligibility."
        ),
    }


def _normalize_match_text(value: str) -> str:
    """Normalize clinical text for conservative phrase/token matching."""
    cleaned = "".join(
        character.casefold() if character.isalnum() else " "
        for character in value
    )
    return " ".join(cleaned.split())


def _clinical_text_matches(left: str, right: str) -> bool:
    """Conservatively compare two clinical phrases without synonym guessing."""
    left_normalized = _normalize_match_text(left)
    right_normalized = _normalize_match_text(right)

    if not left_normalized or not right_normalized:
        return False

    if left_normalized in right_normalized or right_normalized in left_normalized:
        return True

    ignored_words = {
        "and", "or", "of", "the", "disease", "disorder", "condition",
        "finding", "syndrome", "mellitus", "unspecified", "chronic",
    }

    left_tokens = {
        token for token in left_normalized.split()
        if token not in ignored_words and len(token) > 1
    }
    right_tokens = {
        token for token in right_normalized.split()
        if token not in ignored_words and len(token) > 1
    }

    if not left_tokens or not right_tokens:
        return False

    return left_tokens.issubset(right_tokens) or right_tokens.issubset(left_tokens)


def _extract_patient_condition_inventory(
    resources: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return active and historical patient Conditions for screening."""
    active: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []

    for resource in resources:
        if resource.get("resourceType") != "Condition":
            continue

        code_summary = _fhir_coding_summary(resource.get("code"))
        name = code_summary.get("text")
        if not isinstance(name, str) or not name.strip():
            continue

        clinical_status = _fhir_status_code(resource.get("clinicalStatus"))
        item = {
            "name": name,
            "clinical_status": clinical_status,
            "system": code_summary.get("system"),
            "code": code_summary.get("code"),
        }

        if clinical_status == "active":
            active.append(item)
        else:
            historical.append(item)

    return {"active": active, "historical": historical}



def _evaluate_target_condition_evidence(
    patient_conditions: list[dict[str, Any]],
    trial_conditions: list[str],
    target_condition: str,
) -> dict[str, Any] | None:
    """
    Evaluate patient evidence specifically for the condition that caused the
    trial to enter the discovery set.

    This prevents a different condition listed by a multi-condition trial from
    satisfying the ranking condition gate. For example, when the discovery
    target is "Type 2 diabetes", a patient's hypertension must not satisfy the
    target-condition gate merely because the trial also lists hypertension.
    """
    requested = target_condition.strip()

    if not requested:
        return None

    matching_registered_conditions = [
        trial_condition
        for trial_condition in trial_conditions
        if isinstance(trial_condition, str)
        and _condition_matches(
            requested_condition=requested,
            study_conditions=[trial_condition],
        )
    ]

    if not matching_registered_conditions:
        return {
            "criterion_type": "target_condition",
            "target_condition": requested,
            "classification": "POSSIBLE_CONFLICT",
            "target_condition_registered_in_trial": False,
            "matching_registered_trial_conditions": [],
            "patient_matches": [],
            "active_match_found": False,
            "reason": (
                "The requested target condition is not represented in the "
                "trial's registered ClinicalTrials.gov conditions. A trial "
                "that does not represent the discovery target cannot pass "
                "the target-condition evidence gate."
            ),
        }

    matching_patient_conditions = [
        condition
        for condition in patient_conditions
        if _clinical_text_matches(
            requested,
            str(condition.get("name") or ""),
        )
    ]

    if matching_patient_conditions:
        active_matches = [
            condition
            for condition in matching_patient_conditions
            if condition.get("clinical_status") == "active"
        ]

        return {
            "criterion_type": "target_condition",
            "target_condition": requested,
            "classification": "MATCH",
            "target_condition_registered_in_trial": True,
            "matching_registered_trial_conditions": (
                matching_registered_conditions[:5]
            ),
            "patient_matches": matching_patient_conditions[:5],
            "active_match_found": bool(active_matches),
            "reason": (
                f"Direct patient Condition evidence was found for the "
                f"requested target condition '{requested}'. The target "
                "condition is also represented in the trial's registered "
                "ClinicalTrials.gov conditions."
            ),
        }

    return {
        "criterion_type": "target_condition",
        "target_condition": requested,
        "classification": "POSSIBLE_CONFLICT",
        "target_condition_registered_in_trial": True,
        "matching_registered_trial_conditions": (
            matching_registered_conditions[:5]
        ),
        "patient_matches": [],
        "active_match_found": False,
        "reason": (
            f"No direct matching FHIR Condition was found for the requested "
            f"target condition '{requested}'. Other patient conditions do "
            "not satisfy this target-condition gate."
        ),
    }



def _summarize_unknown_structured_criteria(
    structured_eligibility: dict[str, Any] | None,
    maximum_items: int | None = None,
    trial_minimum_age: str | None = None,
    trial_maximum_age: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return structured trial criteria that still require human review.

    By default the complete set is returned internally so exact unresolved
    counts can be calculated. A presentation limit may be requested by callers
    when only a preview is needed.
    """
    if not isinstance(structured_eligibility, dict):
        return []

    minimum_age_years = _parse_age_years(trial_minimum_age)
    maximum_age_years = _parse_age_years(trial_maximum_age)

    unknown_items: list[dict[str, Any]] = []
    for characteristic in structured_eligibility.get("characteristics", []):
        if not isinstance(characteristic, dict):
            continue

        criterion = characteristic.get("criterion")
        value = characteristic.get("value")
        if criterion is None and value is None:
            continue

        normalized_value = _normalize_match_text(str(value or ""))

        if normalized_value in {
            "inclusion criteria",
            "exclusion criteria",
            "eligibility criteria",
        }:
            continue

        if minimum_age_years is not None:
            min_age_int = int(minimum_age_years)
            age_phrases = {
                f"at least {min_age_int} years old",
                f"at least {min_age_int} years",
                f"minimum age {min_age_int}",
            }
            if any(phrase in normalized_value for phrase in age_phrases):
                continue

        if maximum_age_years is not None:
            max_age_int = int(maximum_age_years)
            age_phrases = {
                f"no more than {max_age_int} years old",
                f"no more than {max_age_int} years",
                f"maximum age {max_age_int}",
                f"up to {max_age_int} years old",
            }
            if any(phrase in normalized_value for phrase in age_phrases):
                continue

        unknown_items.append(
            {
                "criterion": criterion,
                "exclude": characteristic.get("exclude"),
                "value_type": characteristic.get("value_type"),
                "value": value,
                "classification": "UNKNOWN",
                "reason": (
                    "This structured eligibility requirement is not safely "
                    "determinable from the supported patient FHIR fields by "
                    "the current TrialScout screening rules."
                ),
            }
        )

        if maximum_items is not None and len(unknown_items) >= maximum_items:
            break

    return unknown_items



async def _fetch_trial_for_screening(
    nct_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch the official ClinicalTrials.gov record used for screening."""
    try:
        async with httpx.AsyncClient(timeout=CLINICAL_TRIALS_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{CLINICAL_TRIALS_API}/studies/{nct_id}")
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return None, "ClinicalTrials.gov did not respond before timeout."
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, f"No trial was found for {nct_id}."
        return None, f"ClinicalTrials.gov returned HTTP status {exc.response.status_code}."
    except httpx.RequestError as exc:
        return None, f"Unable to connect to ClinicalTrials.gov: {exc}"
    except ValueError:
        return None, "ClinicalTrials.gov returned invalid JSON."

    return payload, None


async def _fetch_trial_fhir_for_screening(
    nct_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch the FEvIR ClinicalTrials.gov-to-FHIR Bundle for screening."""
    fevir_api_token = os.getenv("FEVIR_API_TOKEN", "").strip()
    if not fevir_api_token:
        return None, (
            "FEVIR_API_TOKEN is not set, so structured trial FHIR "
            "eligibility could not be retrieved."
        )

    converter_request = {
        "functionid": "submitnctid",
        "nctid": nct_id,
        "apiToken": fevir_api_token,
        "addtodatabase": False,
    }

    try:
        async with httpx.AsyncClient(timeout=FEVIR_TIMEOUT_SECONDS) as client:
            response = await client.post(
                FEVIR_API,
                json=converter_request,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            converter_payload = response.json()
    except httpx.TimeoutException:
        return None, (
            "The ClinicalTrials.gov-to-FHIR converter did not respond "
            "before timeout."
        )
    except httpx.HTTPStatusError as exc:
        return None, (
            "The ClinicalTrials.gov-to-FHIR converter returned HTTP "
            f"status {exc.response.status_code}."
        )
    except httpx.RequestError as exc:
        return None, f"Unable to connect to the FHIR converter: {exc}"
    except ValueError:
        return None, "The FHIR converter returned invalid JSON."

    fhir_bundle = _find_fhir_bundle(converter_payload)
    if fhir_bundle is None:
        return None, "The converter response did not contain a FHIR Bundle."

    return fhir_bundle, None


def _find_screening_classification(
    screening: dict[str, Any],
    criterion_type: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Find screening items for one deterministic criterion type."""
    matches = [
        item
        for item in screening.get("matched_facts", [])
        if isinstance(item, dict)
        and item.get("criterion_type") == criterion_type
    ]
    conflicts = [
        item
        for item in screening.get("possible_conflicts", [])
        if isinstance(item, dict)
        and item.get("criterion_type") == criterion_type
    ]
    unknowns = [
        item
        for item in screening.get("unknown_requirements", [])
        if isinstance(item, dict)
        and item.get("criterion_type") == criterion_type
    ]

    if matches:
        return "MATCH", matches
    if conflicts:
        return "POSSIBLE_CONFLICT", conflicts
    if unknowns:
        return "UNKNOWN", unknowns
    return "UNKNOWN", []



def _registered_condition_evidence(
    screening: dict[str, Any],
) -> dict[str, Any]:
    """
    Summarize direct patient evidence across registered trial conditions.

    Levels:
      FULL    - direct evidence for every registered trial condition
      PARTIAL - direct evidence for some, but not all, registered conditions
      NONE    - no direct registered-condition evidence found
      UNKNOWN - trial conditions could not be evaluated
    """
    trial = screening.get("trial", {})
    trial_conditions = trial.get("conditions", [])

    if not isinstance(trial_conditions, list):
        trial_conditions = []

    normalized_trial_conditions = [
        condition
        for condition in trial_conditions
        if isinstance(condition, str) and condition.strip()
    ]

    matched_by_condition: dict[str, dict[str, Any]] = {}
    conflict_by_condition: dict[str, dict[str, Any]] = {}

    for item in screening.get("matched_facts", []):
        if (
            isinstance(item, dict)
            and item.get("criterion_type") == "condition"
            and isinstance(item.get("trial_condition"), str)
        ):
            matched_by_condition[item["trial_condition"]] = item

    for item in screening.get("possible_conflicts", []):
        if (
            isinstance(item, dict)
            and item.get("criterion_type") == "condition"
            and isinstance(item.get("trial_condition"), str)
        ):
            conflict_by_condition[item["trial_condition"]] = item

    per_condition: list[dict[str, Any]] = []
    matched_conditions: list[str] = []
    unmatched_conditions: list[str] = []

    for condition in normalized_trial_conditions:
        if condition in matched_by_condition:
            classification = "MATCH"
            matched_conditions.append(condition)
            reason = matched_by_condition[condition].get("reason")
        elif condition in conflict_by_condition:
            classification = "NO_DIRECT_EVIDENCE"
            unmatched_conditions.append(condition)
            reason = conflict_by_condition[condition].get("reason")
        else:
            classification = "UNKNOWN"
            reason = (
                "The condition could not be deterministically evaluated from "
                "the supported patient FHIR data."
            )

        per_condition.append(
            {
                "trial_condition": condition,
                "classification": classification,
                "reason": reason,
            }
        )

    if not normalized_trial_conditions:
        level = "UNKNOWN"
    elif len(matched_conditions) == len(normalized_trial_conditions):
        level = "FULL"
    elif matched_conditions:
        level = "PARTIAL"
    elif unmatched_conditions:
        level = "NONE"
    else:
        level = "UNKNOWN"

    return {
        "scope": "ALL_REGISTERED_TRIAL_CONDITIONS",
        "level": level,
        "registered_conditions": normalized_trial_conditions,
        "matched_conditions": matched_conditions,
        "unmatched_conditions": unmatched_conditions,
        "per_condition": per_condition,
    }


def _build_preliminary_alignment_assessment(
    screening: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a qualitative, deterministic patient-to-trial alignment assessment.

    This deliberately avoids numerical compatibility scores and arbitrary
    point weights. It summarizes only evidence TrialScout can evaluate safely.
    """
    target_condition = str(
        screening.get("target_condition") or ""
    ).strip()
    target_evidence = screening.get("target_condition_evidence")

    registered_condition_evidence = _registered_condition_evidence(screening)

    if target_condition and isinstance(target_evidence, dict):
        target_status = str(
            target_evidence.get("classification") or "UNKNOWN"
        ).upper()

        if target_status == "MATCH":
            condition_level = "FULL"
        elif target_status == "POSSIBLE_CONFLICT":
            condition_level = "NONE"
        else:
            condition_level = "UNKNOWN"

        condition_scope = "REQUESTED_TARGET_CONDITION"
        condition_reason = target_evidence.get("reason")
        condition_gate_triggered = target_status != "MATCH"
    else:
        target_status = None
        condition_level = registered_condition_evidence.get(
            "level",
            "UNKNOWN",
        )
        condition_scope = "ALL_REGISTERED_TRIAL_CONDITIONS"

        if condition_level == "FULL":
            condition_reason = (
                "Direct patient Condition evidence was found for every "
                "registered trial condition."
            )
        elif condition_level == "PARTIAL":
            condition_reason = (
                "Direct patient Condition evidence was found for some, but "
                "not all, registered trial conditions."
            )
        elif condition_level == "NONE":
            condition_reason = (
                "No direct patient Condition evidence was found for the "
                "registered trial conditions."
            )
        else:
            condition_reason = (
                "Registered-condition evidence could not be deterministically "
                "evaluated."
            )

        condition_gate_triggered = condition_level in {"NONE", "UNKNOWN"}

    age_status, age_items = _find_screening_classification(
        screening,
        "age",
    )
    sex_status, sex_items = _find_screening_classification(
        screening,
        "sex",
    )

    trial = screening.get("trial", {})
    overall_status = str(trial.get("overall_status") or "").upper()

    if overall_status == "RECRUITING":
        recruitment_status = "MATCH"
        recruitment_reason = (
            "The official ClinicalTrials.gov record currently reports the "
            "study as RECRUITING."
        )
    elif overall_status:
        recruitment_status = "POSSIBLE_CONFLICT"
        recruitment_reason = (
            "The official ClinicalTrials.gov record is not currently marked "
            "RECRUITING."
        )
    else:
        recruitment_status = "UNKNOWN"
        recruitment_reason = (
            "Current recruitment status could not be confirmed."
        )

    dimensions = [
        {
            "dimension": "condition_evidence",
            "classification": condition_level,
            "match_scope": condition_scope,
            "target_condition": target_condition or None,
            "target_condition_status": target_status,
            "reason": condition_reason,
            "registered_condition_evidence": registered_condition_evidence,
        },
        {
            "dimension": "age",
            "classification": age_status,
            "reason": (
                age_items[0].get("reason")
                if age_items
                else "Age could not be deterministically evaluated."
            ),
        },
        {
            "dimension": "recruitment_status",
            "classification": recruitment_status,
            "reason": recruitment_reason,
            "trial_value": overall_status or None,
        },
        {
            "dimension": "sex",
            "classification": sex_status,
            "reason": (
                sex_items[0].get("reason")
                if sex_items
                else "Sex compatibility could not be deterministically evaluated."
            ),
        },
    ]

    explicit_conflicts = [
        dimension["dimension"]
        for dimension in dimensions[1:]
        if dimension.get("classification") == "POSSIBLE_CONFLICT"
    ]

    supported_matches = [
        dimension["dimension"]
        for dimension in dimensions[1:]
        if dimension.get("classification") == "MATCH"
    ]

    supported_unknowns = [
        dimension["dimension"]
        for dimension in dimensions[1:]
        if dimension.get("classification") == "UNKNOWN"
    ]

    # Qualitative alignment logic. No numerical thresholds are used.
    if target_condition and target_status != "MATCH":
        alignment_band = "LIMITED_SUPPORTED_ALIGNMENT"
    elif recruitment_status == "POSSIBLE_CONFLICT":
        alignment_band = "LIMITED_SUPPORTED_ALIGNMENT"
    elif explicit_conflicts:
        alignment_band = "LIMITED_SUPPORTED_ALIGNMENT"
    elif condition_level == "NONE":
        alignment_band = "LIMITED_SUPPORTED_ALIGNMENT"
    elif condition_level == "UNKNOWN":
        alignment_band = "INSUFFICIENT_SUPPORTED_EVIDENCE"
    elif condition_level == "PARTIAL":
        alignment_band = "MIXED_SUPPORTED_ALIGNMENT"
    elif supported_unknowns:
        alignment_band = "MIXED_SUPPORTED_ALIGNMENT"
    else:
        alignment_band = "STRONGER_SUPPORTED_ALIGNMENT"

    result_counts = screening.get("result_counts", {})
    unknown_requirement_count = int(
        result_counts.get("unknown_requirements") or 0
    )

    evidence_scope = (
        "BASIC_DETERMINISTIC_FACTS_WITH_UNRESOLVED_ELIGIBILITY"
        if unknown_requirement_count > 0
        else
        "BASIC_DETERMINISTIC_FACTS_ONLY"
    )

    return {
        "assessment_type": "QUALITATIVE_DETERMINISTIC_ALIGNMENT",
        "alignment_band": alignment_band,
        "evidence_scope": evidence_scope,
        "unresolved_eligibility_present": unknown_requirement_count > 0,
        "unknown_requirement_count": unknown_requirement_count,
        "condition_evidence": {
            "level": condition_level,
            "scope": condition_scope,
            "target_condition": target_condition or None,
            "target_condition_status": target_status,
            "gate_triggered": condition_gate_triggered,
            "reason": condition_reason,
            "registered_condition_evidence": registered_condition_evidence,
        },
        "supported_matches": supported_matches,
        "explicit_conflicts": explicit_conflicts,
        "supported_unknowns": supported_unknowns,
        "dimensions": dimensions,
        "important_interpretation": (
            "This is a deterministic preliminary alignment assessment based "
            "only on direct condition evidence, published age range, current "
            "recruitment status, and published sex restriction. It is not an "
            "eligibility probability, medical recommendation, or substitute "
            "for study-team review."
        ),
    }


def _alignment_ranking_key(
    item: dict[str, Any],
) -> tuple[Any, ...]:
    """
    Deterministically order trials without numerical compatibility scoring.

    Priority:
      1. Target/condition gate passed before triggered/unknown.
      2. Recruiting before unknown/non-recruiting.
      3. Fewer deterministic age/sex conflicts.
      4. Condition evidence FULL > PARTIAL > NONE > UNKNOWN.
      5. More supported basic-fact matches.
      6. Stable NCT identifier tie-breaker.
    """
    gate_triggered = item.get("condition_gate_triggered")
    gate_priority = 0 if gate_triggered is False else 1

    recruitment = str(item.get("recruitment_status") or "UNKNOWN")
    recruitment_priority = {
        "MATCH": 0,
        "UNKNOWN": 1,
        "POSSIBLE_CONFLICT": 2,
    }.get(recruitment, 3)

    explicit_conflict_count = item.get("explicit_conflict_count")
    if not isinstance(explicit_conflict_count, int):
        explicit_conflict_count = 999999

    condition_level = str(item.get("condition_evidence_level") or "UNKNOWN")
    condition_priority = {
        "FULL": 0,
        "PARTIAL": 1,
        "NONE": 2,
        "UNKNOWN": 3,
    }.get(condition_level, 4)

    supported_match_count = item.get("supported_match_count")
    if not isinstance(supported_match_count, int):
        supported_match_count = 0

    return (
        gate_priority,
        recruitment_priority,
        explicit_conflict_count,
        condition_priority,
        -supported_match_count,
        str(item.get("nct_id") or ""),
    )






def _extract_geocoding_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract one deterministic geocoding result from Google Maps output."""
    results = payload.get("results", [])
    if not isinstance(results, list) or not results:
        return None

    first = results[0]
    if not isinstance(first, dict):
        return None

    geometry = first.get("geometry", {})
    location = geometry.get("location", {}) if isinstance(geometry, dict) else {}

    latitude = location.get("lat") if isinstance(location, dict) else None
    longitude = location.get("lng") if isinstance(location, dict) else None

    if not isinstance(latitude, (int, float)):
        return None
    if not isinstance(longitude, (int, float)):
        return None

    return {
        "formatted_address": first.get("formatted_address"),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "place_id": first.get("place_id"),
        "location_type": (
            geometry.get("location_type")
            if isinstance(geometry, dict)
            else None
        ),
        "partial_match": first.get("partial_match") is True,
        "types": first.get("types", []),
    }


async def _geocode_location_internal(
    location_query: str,
) -> dict[str, Any]:
    """Resolve a city, ZIP code, or address into latitude/longitude."""
    query = location_query.strip()

    if not query:
        return {
            "success": False,
            "error": "A location, ZIP code, or address is required.",
        }

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

    if not api_key:
        return {
            "success": False,
            "configuration_required": True,
            "error": (
                "GOOGLE_MAPS_API_KEY is not configured, so TrialScout cannot "
                "geocode a city, ZIP code, or address yet."
            ),
            "next_step": (
                "Enable the Google Maps Geocoding API for the GCP project and "
                "set GOOGLE_MAPS_API_KEY on the TrialScout Cloud Run service."
            ),
        }

    try:
        async with httpx.AsyncClient(
            timeout=GEOCODING_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(
                GOOGLE_GEOCODING_API,
                params={
                    "address": query,
                    "key": api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "The geocoding service did not respond before timeout.",
        }
    except httpx.HTTPStatusError as exc:
        return {
            "success": False,
            "error": (
                "The geocoding service returned HTTP status "
                f"{exc.response.status_code}."
            ),
        }
    except httpx.RequestError as exc:
        return {
            "success": False,
            "error": f"Unable to connect to the geocoding service: {exc}",
        }
    except ValueError:
        return {
            "success": False,
            "error": "The geocoding service returned invalid JSON.",
        }

    status = str(payload.get("status") or "")
    if status != "OK":
        return {
            "success": False,
            "error": (
                "The requested location could not be geocoded."
                if status == "ZERO_RESULTS"
                else f"Geocoding failed with status {status or 'UNKNOWN'}."
            ),
            "geocoding_status": status or None,
            "error_message": payload.get("error_message"),
        }

    resolved = _extract_geocoding_result(payload)
    if resolved is None:
        return {
            "success": False,
            "error": (
                "The geocoding service returned no usable geographic "
                "coordinates."
            ),
        }

    return {
        "success": True,
        "source": "Google Maps Geocoding API",
        "requested_location": query,
        **resolved,
        "important_notice": (
            "The returned coordinates represent the geocoder's resolved "
            "location. TrialScout uses them only as an origin for geographic "
            "trial-site distance filtering."
        ),
    }


@mcp.tool()
@discovery_mcp.tool()
async def geocode_location(
    location_query: str,
) -> dict[str, Any]:
    """
    Convert a city, ZIP code, place, or address into latitude/longitude.

    Use this tool before a radius-based trial search when the user provides
    human-readable geography such as "21201", "Laurel, Maryland", or an
    address instead of coordinates.

    Args:
        location_query: City, ZIP code, place, or address to geocode.
    """
    return await _geocode_location_internal(location_query)

@mcp.tool()
@discovery_mcp.tool()
@analysis_mcp.tool()
@fhir_mcp.tool()
@matching_mcp.tool()
def health_check() -> dict[str, str]:
    """Verify that the TrialScout MCP server is running correctly."""
    return {
        "status": "healthy",
        "service": "TrialScout MCP Server",
    }


@mcp.tool()
@discovery_mcp.tool()

async def search_clinical_trials(
    condition: str,
    location: str = "",
    age: int | None = None,
    phase: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    search_radius_miles: int | None = None,
    recruiting_only: bool = True,
    maximum_results: int = 5,
) -> dict[str, Any]:
    """
    Search current ClinicalTrials.gov studies by condition, location, age,
    phase, and optional travel radius.

    Exact-location mode:
        Supply location without a radius.

    Radius-search mode:
        Supply search_radius_miles plus either:
        - latitude and longitude, or
        - a human-readable location/ZIP code that TrialScout can geocode.

    The ClinicalTrials.gov API is paginated. TrialScout continues through
    pages until it finds the requested number of locally validated studies,
    exhausts the API results, or reaches the configured safety page limit.

    Args:
        condition: Disease or condition, such as "Type 2 diabetes".
        location: Optional city, state, ZIP code, region, country, or origin.
        age: Optional participant age in completed years.
        phase: Optional exact study phase.
        latitude: Optional radius-search origin latitude.
        longitude: Optional radius-search origin longitude.
        search_radius_miles: Optional radius in miles.
        recruiting_only: Return only studies currently recruiting when true.
        maximum_results: Requested matching-study count.
    """
    condition = condition.strip()
    location = location.strip()
    phase = phase.strip()

    requested_phase, phase_error = _normalize_phase_filter(phase)

    if phase_error is not None:
        return {
            "success": False,
            "error": phase_error,
            "studies": [],
        }

    if not condition:
        return {
            "success": False,
            "error": "A medical condition is required.",
            "studies": [],
        }

    if age is not None and not MIN_PARTICIPANT_AGE <= age <= MAX_PARTICIPANT_AGE:
        return {
            "success": False,
            "error": (
                f"Age must be between {MIN_PARTICIPANT_AGE} and "
                f"{MAX_PARTICIPANT_AGE}."
            ),
            "studies": [],
        }

    radius_search_requested = search_radius_miles is not None
    geocoding_result: dict[str, Any] | None = None

    if radius_search_requested:
        if not 1 <= int(search_radius_miles) <= MAX_SEARCH_RADIUS_MILES:
            return {
                "success": False,
                "error": (
                    "Search radius must be between 1 and "
                    f"{MAX_SEARCH_RADIUS_MILES} miles."
                ),
                "studies": [],
            }

        # When coordinates were not supplied, resolve the user's human-readable
        # origin. This keeps radius search usable for ZIP codes/cities.
        if latitude is None and longitude is None:
            if not location:
                return {
                    "success": False,
                    "error": (
                        "A location/ZIP code or latitude/longitude is required "
                        "for a radius search."
                    ),
                    "studies": [],
                }

            geocoding_result = await _geocode_location_internal(location)
            if not geocoding_result.get("success"):
                return {
                    "success": False,
                    "error": geocoding_result.get(
                        "error",
                        "Unable to geocode the requested search origin.",
                    ),
                    "configuration_required": geocoding_result.get(
                        "configuration_required",
                        False,
                    ),
                    "next_step": geocoding_result.get("next_step"),
                    "studies": [],
                }

            latitude = geocoding_result.get("latitude")
            longitude = geocoding_result.get("longitude")

        if latitude is None or longitude is None:
            return {
                "success": False,
                "error": (
                    "Both latitude and longitude are required when one "
                    "coordinate is supplied."
                ),
                "studies": [],
            }

        if not -90 <= float(latitude) <= 90:
            return {
                "success": False,
                "error": "Latitude must be between -90 and 90.",
                "studies": [],
            }

        if not -180 <= float(longitude) <= 180:
            return {
                "success": False,
                "error": "Longitude must be between -180 and 180.",
                "studies": [],
            }

    elif latitude is not None or longitude is not None:
        return {
            "success": False,
            "error": (
                "search_radius_miles is required when latitude or longitude "
                "is supplied."
            ),
            "studies": [],
        }

    maximum_results = max(
        1,
        min(int(maximum_results), MAX_DISCOVERY_RESULTS),
    )

    base_params: dict[str, str | int | bool] = {
        "query.cond": condition,
        "pageSize": DISCOVERY_PAGE_SIZE,
        "format": "json",
        "countTotal": True,
    }

    if radius_search_requested:
        base_params["query.locn"] = (
            "AREA[LocationGeoPoint] "
            f"DISTANCE[{float(latitude)}, {float(longitude)}, "
            f"{int(search_radius_miles)}mi]"
        )
    elif location:
        base_params["query.locn"] = location

    if recruiting_only:
        base_params["filter.overallStatus"] = "RECRUITING"

    requested_location_parts = [
        part.strip().casefold()
        for part in location.split(",")
        if part.strip()
    ]

    matching_studies: list[dict[str, Any]] = []
    rejected_condition_mismatch_count = 0
    rejected_phase_mismatch_count = 0
    rejected_age_mismatch_count = 0
    rejected_location_mismatch_count = 0

    api_total_count: int | None = None
    next_page_token: str | None = None
    pages_fetched = 0
    api_candidates_examined = 0

    try:
        async with httpx.AsyncClient(
            timeout=CLINICAL_TRIALS_TIMEOUT_SECONDS
        ) as client:
            while (
                len(matching_studies) < maximum_results
                and pages_fetched < DISCOVERY_MAX_PAGES
            ):
                params = dict(base_params)
                if next_page_token:
                    params["pageToken"] = next_page_token

                response = await client.get(
                    f"{CLINICAL_TRIALS_API}/studies",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()

                pages_fetched += 1

                if api_total_count is None:
                    total = payload.get("totalCount")
                    api_total_count = total if isinstance(total, int) else None

                studies = payload.get("studies", [])
                if not isinstance(studies, list):
                    studies = []

                api_candidates_examined += len(studies)

                for study in studies:
                    if len(matching_studies) >= maximum_results:
                        break

                    if not isinstance(study, dict):
                        continue

                    protocol = study.get("protocolSection", {})
                    identification = protocol.get("identificationModule", {})
                    status = protocol.get("statusModule", {})
                    design = protocol.get("designModule", {})
                    eligibility = protocol.get("eligibilityModule", {})
                    contacts_locations = protocol.get(
                        "contactsLocationsModule",
                        {},
                    )
                    conditions_module = protocol.get("conditionsModule", {})

                    study_conditions = conditions_module.get("conditions", [])
                    if not isinstance(study_conditions, list):
                        study_conditions = []

                    study_keywords = conditions_module.get("keywords", [])
                    study_phases = design.get("phases", [])
                    if not isinstance(study_phases, list):
                        study_phases = []

                    normalized_study_phases = {
                        str(value).strip().upper()
                        for value in study_phases
                        if isinstance(value, str) and value.strip()
                    }

                    if (
                        requested_phase is not None
                        and requested_phase not in normalized_study_phases
                    ):
                        rejected_phase_mismatch_count += 1
                        continue

                    if not _condition_matches(
                        requested_condition=condition,
                        study_conditions=study_conditions,
                    ):
                        rejected_condition_mismatch_count += 1
                        continue

                    minimum_age_text = eligibility.get("minimumAge")
                    maximum_age_text = eligibility.get("maximumAge")
                    minimum_age_years = _parse_age_years(minimum_age_text)
                    maximum_age_years = _parse_age_years(maximum_age_text)

                    age_matches = True
                    if age is not None:
                        if (
                            minimum_age_years is not None
                            and age < minimum_age_years
                        ):
                            age_matches = False
                        if (
                            maximum_age_years is not None
                            and age > maximum_age_years
                        ):
                            age_matches = False

                    if not age_matches:
                        rejected_age_mismatch_count += 1
                        continue

                    all_locations = contacts_locations.get("locations", [])
                    if not isinstance(all_locations, list):
                        all_locations = []

                    matching_locations: list[dict[str, Any]] = []

                    for location_item in all_locations:
                        if not isinstance(location_item, dict):
                            continue

                        readable_location = _format_location(location_item)
                        if not readable_location:
                            continue

                        location_result: dict[str, Any] = {
                            "facility": location_item.get("facility"),
                            "city": location_item.get("city"),
                            "state": location_item.get("state"),
                            "country": location_item.get("country"),
                            "formatted_location": readable_location,
                            "site_status": location_item.get("status"),
                        }

                        coordinates = _get_location_coordinates(location_item)

                        if coordinates:
                            site_latitude, site_longitude = coordinates
                            location_result["latitude"] = site_latitude
                            location_result["longitude"] = site_longitude
                        else:
                            site_latitude = None
                            site_longitude = None

                        if radius_search_requested:
                            if (
                                site_latitude is not None
                                and site_longitude is not None
                            ):
                                distance_miles = _haversine_distance_miles(
                                    latitude_1=float(latitude),
                                    longitude_1=float(longitude),
                                    latitude_2=site_latitude,
                                    longitude_2=site_longitude,
                                )

                                if distance_miles > float(search_radius_miles):
                                    continue

                                location_result["distance_miles"] = round(
                                    distance_miles,
                                    1,
                                )
                                matching_locations.append(location_result)

                            # Never claim a radius match for a site without
                            # coordinates.
                            continue

                        if requested_location_parts:
                            searchable_location = " ".join(
                                str(value)
                                for value in [
                                    location_item.get("facility"),
                                    location_item.get("city"),
                                    location_item.get("state"),
                                    location_item.get("country"),
                                ]
                                if value
                            ).casefold()

                            if not all(
                                part in searchable_location
                                for part in requested_location_parts
                            ):
                                continue

                        matching_locations.append(location_result)

                    if (
                        location
                        or radius_search_requested
                    ) and not matching_locations:
                        rejected_location_mismatch_count += 1
                        continue

                    if radius_search_requested:
                        matching_locations.sort(
                            key=lambda item: item.get(
                                "distance_miles",
                                float("inf"),
                            )
                        )

                    nct_id = identification.get("nctId")

                    matching_studies.append(
                        {
                            "nct_id": nct_id,
                            "title": identification.get("briefTitle"),
                            "official_title": identification.get(
                                "officialTitle"
                            ),
                            "conditions": study_conditions,
                            "keywords": study_keywords,
                            "condition_matches": True,
                            "condition_match_basis": (
                                "ClinicalTrials.gov registered conditions field"
                            ),
                            "overall_status": status.get("overallStatus"),
                            "study_type": design.get("studyType"),
                            "phases": study_phases,
                            "phase_matches": (
                                requested_phase is None
                                or requested_phase in normalized_study_phases
                            ),
                            "minimum_age": minimum_age_text,
                            "maximum_age": maximum_age_text,
                            "requested_age": age,
                            "age_matches": age_matches,
                            "sex": eligibility.get("sex"),
                            "healthy_volunteers": eligibility.get(
                                "healthyVolunteers"
                            ),
                            "eligibility_summary": _shorten_text(
                                eligibility.get("eligibilityCriteria"),
                                maximum_length=1200,
                            ),
                            "matching_locations": matching_locations[:5],
                            "clinicaltrials_url": (
                                f"https://clinicaltrials.gov/study/{nct_id}"
                                if nct_id
                                else None
                            ),
                        }
                    )

                raw_next_token = payload.get("nextPageToken")
                next_page_token = (
                    raw_next_token
                    if isinstance(raw_next_token, str) and raw_next_token
                    else None
                )

                if not next_page_token:
                    break

    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "ClinicalTrials.gov did not respond before timeout.",
            "studies": [],
        }
    except httpx.HTTPStatusError as exc:
        return {
            "success": False,
            "error": (
                "ClinicalTrials.gov returned HTTP status "
                f"{exc.response.status_code}."
            ),
            "studies": [],
        }
    except httpx.RequestError as exc:
        return {
            "success": False,
            "error": f"Unable to connect to ClinicalTrials.gov: {exc}",
            "studies": [],
        }
    except ValueError:
        return {
            "success": False,
            "error": "ClinicalTrials.gov returned invalid JSON.",
            "studies": [],
        }

    if radius_search_requested:
        search_mode = "radius"
    elif location:
        search_mode = "exact_location"
    else:
        search_mode = "condition_only"

    pagination_limit_reached = (
        len(matching_studies) < maximum_results
        and bool(next_page_token)
        and pages_fetched >= DISCOVERY_MAX_PAGES
    )

    return {
        "success": True,
        "source": "ClinicalTrials.gov API v2",
        "condition": condition,
        "requested_location": location or None,
        "requested_age": age,
        "requested_phase": requested_phase,
        "requested_phase_label": phase or None,
        "recruiting_only": recruiting_only,
        "search_mode": search_mode,
        "search_origin": {
            "location_label": location or None,
            "latitude": latitude,
            "longitude": longitude,
            "geocoded": geocoding_result is not None,
            "formatted_geocoded_address": (
                geocoding_result.get("formatted_address")
                if geocoding_result
                else None
            ),
        },
        "search_radius_miles": search_radius_miles,
        "distance_method": (
            "Straight-line distance calculated by TrialScout from the "
            "resolved search origin to ClinicalTrials.gov site coordinates."
            if radius_search_requested
            else None
        ),
        "api_total_count": api_total_count,
        "api_candidates_examined": api_candidates_examined,
        "pages_fetched": pages_fetched,
        "pagination_limit_reached": pagination_limit_reached,
        "returned_matching_count": len(matching_studies),
        "requested_matching_count": maximum_results,
        "rejected_condition_mismatch_count": (
            rejected_condition_mismatch_count
        ),
        "rejected_phase_mismatch_count": rejected_phase_mismatch_count,
        "rejected_age_mismatch_count": rejected_age_mismatch_count,
        "rejected_location_mismatch_count": rejected_location_mismatch_count,
        "phase_filter_method": (
            "Requested phase is validated against the structured "
            "ClinicalTrials.gov designModule.phases values."
            if requested_phase is not None
            else None
        ),
        "condition_relevance_method": (
            "Candidate studies must match the requested condition against "
            "ClinicalTrials.gov conditionsModule.conditions. Keywords alone "
            "do not qualify a study."
        ),
        "studies": matching_studies,
        "important_notice": (
            "Results passed TrialScout's supported registered-condition, "
            "recruitment, location/radius, age, and requested-phase checks. "
            "Radius values are straight-line estimates, not driving distance. "
            + (
                "The configured pagination safety limit was reached before "
                "the API was exhausted, so additional matching studies may "
                "exist."
                if pagination_limit_reached
                else
                "The search stopped after the requested count was found or "
                "the available API pages were exhausted."
            )
            + " Final eligibility must be confirmed by the official study team."
        ),
    }



@mcp.tool()
@analysis_mcp.tool()
async def get_trial_details(
    nct_id: str,
    location_filter: str = "",
    maximum_locations: int = 10,
) -> dict[str, Any]:
    """
    Retrieve the complete official record for one clinical trial.

    Use this tool after a search when the user asks for detailed eligibility,
    interventions, contacts, study design, or locations for a specific trial.

    Args:
        nct_id: ClinicalTrials.gov identifier, such as "NCT07064473".
        location_filter: Optional city, state, region, or country. When
            supplied, return only locations matching this value.
        maximum_locations: Maximum locations to return, from 1 to 25.
    """
    normalized_nct_id = nct_id.strip().upper()
    location_filter = location_filter.strip()
    maximum_locations = max(1, min(maximum_locations, MAX_LOCATION_RESULTS))

    if (
        not normalized_nct_id.startswith("NCT")
        or len(normalized_nct_id) != 11
        or not normalized_nct_id[3:].isdigit()
    ):
        return {
            "success": False,
            "error": (
                "A valid NCT identifier is required, for example "
                "NCT07064473."
            ),
        }

    try:
        async with httpx.AsyncClient(timeout=CLINICAL_TRIALS_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{CLINICAL_TRIALS_API}/studies/{normalized_nct_id}"
            )
            response.raise_for_status()
            study = response.json()

    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "ClinicalTrials.gov did not respond before timeout.",
        }

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                "success": False,
                "error": f"No trial was found for {normalized_nct_id}.",
            }

        return {
            "success": False,
            "error": (
                "ClinicalTrials.gov returned HTTP status "
                f"{exc.response.status_code}."
            ),
        }

    except httpx.RequestError as exc:
        return {
            "success": False,
            "error": f"Unable to connect to ClinicalTrials.gov: {exc}",
        }

    except ValueError:
        return {
            "success": False,
            "error": "ClinicalTrials.gov returned invalid JSON.",
        }

    protocol = study.get("protocolSection", {})

    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    description = protocol.get("descriptionModule", {})
    conditions = protocol.get("conditionsModule", {})
    design = protocol.get("designModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    contacts = protocol.get("contactsLocationsModule", {})

    requested_parts = [
        part.strip().casefold()
        for part in location_filter.split(",")
        if part.strip()
    ]

    matching_locations: list[dict[str, Any]] = []

    for location_item in contacts.get("locations", []):
        readable_location = _format_location(location_item)

        if not readable_location:
            continue

        if requested_parts:
            searchable_location = " ".join(
                str(value)
                for value in [
                    location_item.get("facility"),
                    location_item.get("city"),
                    location_item.get("state"),
                    location_item.get("country"),
                ]
                if value
            ).casefold()

            if not all(
                part in searchable_location
                for part in requested_parts
            ):
                continue

        location_result: dict[str, Any] = {
            "facility": location_item.get("facility"),
            "city": location_item.get("city"),
            "state": location_item.get("state"),
            "country": location_item.get("country"),
            "formatted_location": readable_location,
        }

        coordinates = _get_location_coordinates(location_item)

        if coordinates:
            site_latitude, site_longitude = coordinates
            location_result["latitude"] = site_latitude
            location_result["longitude"] = site_longitude

        matching_locations.append(location_result)

        if len(matching_locations) >= maximum_locations:
            break

    nct_value = identification.get("nctId")

    return {
        "success": True,
        "source": "ClinicalTrials.gov API v2",
        "nct_id": nct_value,
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "organization": identification.get("organization"),
        "overall_status": status.get("overallStatus"),
        "start_date": status.get("startDateStruct"),
        "completion_date": status.get("completionDateStruct"),
        "brief_summary": description.get("briefSummary"),
        "detailed_description": description.get("detailedDescription"),
        "conditions": conditions.get("conditions", []),
        "keywords": conditions.get("keywords", []),
        "study_type": design.get("studyType"),
        "phases": design.get("phases", []),
        "enrollment": design.get("enrollmentInfo"),
        "interventions": arms.get("interventions", []),
        "minimum_age": eligibility.get("minimumAge"),
        "maximum_age": eligibility.get("maximumAge"),
        "sex": eligibility.get("sex"),
        "healthy_volunteers": eligibility.get("healthyVolunteers"),
        "eligibility_criteria": eligibility.get("eligibilityCriteria"),
        "central_contacts": contacts.get("centralContacts", []),
        "requested_location_filter": location_filter or None,
        "returned_location_count": len(matching_locations),
        "locations": matching_locations,
        "clinicaltrials_url": (
            f"https://clinicaltrials.gov/study/{nct_value}"
            if nct_value
            else None
        ),
        "important_notice": (
            "This record is for research assistance only. Final eligibility "
            "must be confirmed by the official study team."
        ),
    }



def _normalize_ctg_contact(contact: Any) -> dict[str, Any] | None:
    """Normalize a ClinicalTrials.gov central or site contact."""
    if not isinstance(contact, dict):
        return None

    result = {
        "name": contact.get("name"),
        "role": contact.get("role"),
        "phone": contact.get("phone"),
        "phone_extension": contact.get("phoneExt"),
        "email": contact.get("email"),
    }

    if not any(value for value in result.values()):
        return None

    return result


@mcp.tool()
@analysis_mcp.tool()
async def get_trial_contact_next_steps(
    nct_id: str,
    location_filter: str = "",
    origin_location: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    maximum_sites: int = 5,
) -> dict[str, Any]:
    """
    Retrieve published study contacts, relevant sites, and safe next steps.

    This tool is intended for the practical step after a user has identified
    a trial and asks how to contact the study or what to do next.

    Args:
        nct_id: ClinicalTrials.gov identifier.
        location_filter: Optional city/state/country filter.
        origin_location: Optional city, ZIP code, or address used to identify
            the nearest site when coordinates were not supplied.
        latitude: Optional origin latitude for distance sorting.
        longitude: Optional origin longitude for distance sorting.
        maximum_sites: Maximum relevant study sites to return.
    """
    normalized_nct_id = nct_id.strip().upper()
    location_filter = location_filter.strip()
    origin_location = origin_location.strip()
    maximum_sites = max(
        1,
        min(int(maximum_sites), CONTACT_SITE_PREVIEW_LIMIT),
    )

    if (
        not normalized_nct_id.startswith("NCT")
        or len(normalized_nct_id) != 11
        or not normalized_nct_id[3:].isdigit()
    ):
        return {
            "success": False,
            "error": "A valid NCT identifier is required.",
        }

    origin_geocode: dict[str, Any] | None = None

    if origin_location and latitude is None and longitude is None:
        origin_geocode = await _geocode_location_internal(origin_location)

        if not origin_geocode.get("success"):
            return {
                "success": False,
                "error": origin_geocode.get(
                    "error",
                    "Unable to geocode the requested origin.",
                ),
                "configuration_required": origin_geocode.get(
                    "configuration_required",
                    False,
                ),
                "next_step": origin_geocode.get("next_step"),
            }

        latitude = origin_geocode.get("latitude")
        longitude = origin_geocode.get("longitude")

    if (latitude is None) != (longitude is None):
        return {
            "success": False,
            "error": (
                "Provide both latitude and longitude, or neither coordinate."
            ),
        }

    trial_payload, trial_error = await _fetch_trial_for_screening(
        normalized_nct_id
    )
    if trial_error is not None or trial_payload is None:
        return {
            "success": False,
            "error": trial_error or "Unable to retrieve the trial.",
        }

    protocol = trial_payload.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    contacts_locations = protocol.get("contactsLocationsModule", {})

    central_contacts: list[dict[str, Any]] = []
    for contact in contacts_locations.get("centralContacts", []):
        normalized = _normalize_ctg_contact(contact)
        if normalized:
            central_contacts.append(normalized)

    requested_parts = [
        part.strip().casefold()
        for part in location_filter.split(",")
        if part.strip()
    ]

    sites: list[dict[str, Any]] = []

    for location in contacts_locations.get("locations", []):
        if not isinstance(location, dict):
            continue

        searchable_location = " ".join(
            str(value)
            for value in [
                location.get("facility"),
                location.get("city"),
                location.get("state"),
                location.get("zip"),
                location.get("country"),
            ]
            if value
        ).casefold()

        if requested_parts and not all(
            part in searchable_location for part in requested_parts
        ):
            continue

        site_contacts: list[dict[str, Any]] = []
        for contact in location.get("contacts", []):
            normalized = _normalize_ctg_contact(contact)
            if normalized:
                site_contacts.append(normalized)

        site: dict[str, Any] = {
            "facility": location.get("facility"),
            "site_status": location.get("status"),
            "city": location.get("city"),
            "state": location.get("state"),
            "postal_code": location.get("zip"),
            "country": location.get("country"),
            "formatted_location": _format_location(location),
            "contacts": site_contacts,
        }

        coordinates = _get_location_coordinates(location)
        if coordinates:
            site_lat, site_lon = coordinates
            site["latitude"] = site_lat
            site["longitude"] = site_lon

            if latitude is not None and longitude is not None:
                site["distance_miles"] = round(
                    _haversine_distance_miles(
                        latitude_1=float(latitude),
                        longitude_1=float(longitude),
                        latitude_2=site_lat,
                        longitude_2=site_lon,
                    ),
                    1,
                )

        sites.append(site)

    if latitude is not None and longitude is not None:
        sites.sort(
            key=lambda site: (
                site.get("distance_miles", float("inf")),
                str(site.get("facility") or ""),
            )
        )

    sites = sites[:maximum_sites]

    nearest_site = (
        sites[0]
        if sites and isinstance(sites[0].get("distance_miles"), (int, float))
        else None
    )

    return {
        "success": True,
        "source": "ClinicalTrials.gov API v2",
        "nct_id": identification.get("nctId") or normalized_nct_id,
        "brief_title": identification.get("briefTitle"),
        "overall_status": status_module.get("overallStatus"),
        "central_contacts": central_contacts,
        "requested_location_filter": location_filter or None,
        "origin": {
            "location_label": origin_location or None,
            "latitude": latitude,
            "longitude": longitude,
            "formatted_geocoded_address": (
                origin_geocode.get("formatted_address")
                if origin_geocode
                else None
            ),
        },
        "returned_site_count": len(sites),
        "sites": sites,
        "nearest_site": nearest_site,
        "clinicaltrials_url": (
            f"https://clinicaltrials.gov/study/{normalized_nct_id}"
        ),
        "suggested_questions_for_study_team": [
            "Is this site currently enrolling participants?",
            "What are the next screening steps?",
            "Which eligibility requirements need to be confirmed?",
            "What records or information should I have available?",
            "Who should I contact if I have questions about scheduling or travel?",
        ],
        "important_notice": (
            "TrialScout only surfaces contact information published in the "
            "official study record. Contacting a study does not establish "
            "eligibility. Do not change medications or treatment to try to "
            "meet study criteria; the official study team must determine "
            "eligibility."
        ),
    }

@mcp.tool()
@analysis_mcp.tool()
async def get_trial_fhir(
    nct_id: str,
    location_filter: str = "",
    maximum_locations: int = 10,
) -> dict[str, Any]:
    """
    Retrieve and summarize a ClinicalTrials.gov study as HL7 FHIR R6.

    This tool uses the FEvIR ClinicalTrials.gov-to-FHIR converter API to
    generate the same style of ResearchStudy-centered FHIR representation
    used by the ClinicalTrials.gov FHIR pilot.

    Use this tool when the user asks about FHIR, HL7 interoperability,
    standardized trial resources, FHIR study structure, FHIR locations,
    FHIR interventions, or FHIR-based eligibility representation.

    Args:
        nct_id: ClinicalTrials.gov identifier, such as "NCT07064473".
        location_filter: Optional city, state, region, or country used to
            limit returned FHIR Location resources.
        maximum_locations: Maximum number of FHIR Location resources to
            return, from 1 to 25.
    """
    normalized_nct_id = nct_id.strip().upper()
    location_filter = location_filter.strip()
    maximum_locations = max(1, min(maximum_locations, MAX_LOCATION_RESULTS))

    if (
        not normalized_nct_id.startswith("NCT")
        or len(normalized_nct_id) != 11
        or not normalized_nct_id[3:].isdigit()
    ):
        return {
            "success": False,
            "error": (
                "A valid NCT identifier is required, for example "
                "NCT07064473."
            ),
        }

    fevir_api_token = os.getenv("FEVIR_API_TOKEN", "").strip()

    if not fevir_api_token:
        return {
            "success": False,
            "configuration_required": True,
            "error": (
                "FHIR conversion is configured but FEVIR_API_TOKEN is not "
                "set on the TrialScout server."
            ),
            "next_step": (
                "Create or obtain a FEvIR API token and set it as the "
                "FEVIR_API_TOKEN environment variable."
            ),
        }

    converter_request = {
        "functionid": "submitnctid",
        "nctid": normalized_nct_id,
        "apiToken": fevir_api_token,
        "addtodatabase": False,
    }

    try:
        async with httpx.AsyncClient(timeout=FEVIR_TIMEOUT_SECONDS) as client:
            response = await client.post(
                FEVIR_API,
                json=converter_request,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            converter_payload = response.json()

    except httpx.TimeoutException:
        return {
            "success": False,
            "error": (
                "The ClinicalTrials.gov-to-FHIR converter did not respond "
                "before timeout."
            ),
        }

    except httpx.HTTPStatusError as exc:
        return {
            "success": False,
            "error": (
                "The ClinicalTrials.gov-to-FHIR converter returned HTTP "
                f"status {exc.response.status_code}."
            ),
        }

    except httpx.RequestError as exc:
        return {
            "success": False,
            "error": f"Unable to connect to the FHIR converter: {exc}",
        }

    except ValueError:
        return {
            "success": False,
            "error": "The FHIR converter returned invalid JSON.",
        }

    fhir_bundle = _find_fhir_bundle(converter_payload)

    if fhir_bundle is None:
        error_message = None

        if isinstance(converter_payload, dict):
            for key in ("error", "message", "detail"):
                value = converter_payload.get(key)
                if isinstance(value, str) and value.strip():
                    error_message = value.strip()
                    break

        return {
            "success": False,
            "error": (
                error_message
                or "The converter response did not contain a FHIR Bundle."
            ),
        }

    if fhir_bundle.get("resourceType") != "Bundle":
        return {
            "success": False,
            "error": "The converter response was not a valid FHIR Bundle.",
        }

    resources = _flatten_fhir_resources(fhir_bundle)
    resource_counts = _count_fhir_resources(resources)

    main_study = _find_main_fhir_research_study(
        resources=resources,
        nct_id=normalized_nct_id,
    )

    if main_study is None:
        return {
            "success": False,
            "error": (
                "A main ResearchStudy resource could not be identified in "
                "the FHIR Bundle."
            ),
            "bundle_type": fhir_bundle.get("type"),
            "resource_counts": resource_counts,
        }

    fhir_nct_id = _extract_fhir_identifier(
        main_study,
        "clinicaltrials.gov/nctid",
    ) or normalized_nct_id

    official_title = _extract_fhir_official_title(main_study)

    conditions = []
    for condition in main_study.get("condition", []):
        condition_text = _fhir_codeable_text(condition)
        if condition_text:
            conditions.append(condition_text)

    keywords = []
    for keyword in main_study.get("keyword", []):
        keyword_text = _fhir_codeable_text(keyword)
        if keyword_text:
            keywords.append(keyword_text)

    study_design = []
    for design_item in main_study.get("studyDesign", []):
        design_text = _fhir_codeable_text(design_item)
        if design_text:
            study_design.append(design_text)

    progress_statuses = []
    for progress in main_study.get("progressStatus", []):
        if not isinstance(progress, dict):
            continue

        state_text = _fhir_codeable_text(progress.get("state"))
        if not state_text:
            continue

        progress_statuses.append(
            {
                "state": state_text,
                "actual": progress.get("actual"),
                "period": progress.get("period"),
            }
        )

    recruitment = main_study.get("recruitment", {})
    if not isinstance(recruitment, dict):
        recruitment = {}

    eligibility_reference = recruitment.get("eligibility")

    fhir_locations = _extract_fhir_locations(
        resources,
        location_filter,
        maximum_locations,
    )

    return {
        "success": True,
        "source": (
            "ClinicalTrials.gov study data converted to HL7 FHIR through "
            "the FEvIR ClinicalTrials.gov-to-FHIR converter"
        ),
        "fhir_version": FHIR_VERSION,
        "bundle": {
            "resource_type": fhir_bundle.get("resourceType"),
            "bundle_type": fhir_bundle.get("type"),
            "timestamp": fhir_bundle.get("timestamp"),
            "resource_counts": resource_counts,
            "total_resources_parsed": len(resources),
        },
        "study": {
            "nct_id": fhir_nct_id,
            "fhir_resource_id": main_study.get("id"),
            "profiles": _fhir_profiles(main_study),
            "name": main_study.get("name"),
            "brief_title": main_study.get("title"),
            "official_title": official_title,
            "resource_status": main_study.get("status"),
            "primary_purpose": _fhir_codeable_text(
                main_study.get("primaryPurposeType")
            ),
            "phase": _fhir_codeable_text(main_study.get("phase")),
            "conditions": conditions,
            "keywords": keywords,
            "study_design": study_design,
            "description_summary": main_study.get("descriptionSummary"),
            "description": _shorten_text(
                main_study.get("description"),
                maximum_length=2000,
            ),
            "progress_statuses": progress_statuses,
            "target_enrollment": recruitment.get("targetNumber"),
            "eligibility_reference": eligibility_reference,
        },
        "interventions": _extract_fhir_interventions(resources),
        "comparison_groups": _extract_fhir_comparison_groups(resources),
        "structured_eligibility": _extract_fhir_eligibility_group(
            resources,
            fhir_nct_id,
        ),
        "objectives": _extract_fhir_objectives(main_study),
        "central_contacts": _extract_fhir_contacts(resources),
        "requested_location_filter": location_filter or None,
        "returned_location_count": len(fhir_locations),
        "locations": fhir_locations,
        "clinicaltrials_url": (
            f"https://clinicaltrials.gov/study/{fhir_nct_id}"
        ),
        "interoperability_note": (
            "This is an HL7 FHIR R6 research-study representation. It is "
            "not an EHR patient record and does not establish patient "
            "eligibility for the trial."
        ),
    }



def _split_hl7_v2_segments(message: str) -> list[list[str]]:
    """Split a basic HL7 v2 pipe-delimited message into segment fields."""
    normalized = message.replace("\r\n", "\r").replace("\n", "\r")
    raw_segments = [
        segment.strip()
        for segment in normalized.split("\r")
        if segment.strip()
    ]

    if not raw_segments:
        return []

    field_separator = (
        raw_segments[0][3]
        if raw_segments[0].startswith("MSH") and len(raw_segments[0]) > 3
        else "|"
    )

    return [segment.split(field_separator) for segment in raw_segments]


def _hl7_field(
    segment: list[str] | None,
    field_number: int,
) -> str | None:
    """Read a 1-based HL7 field from a split segment."""
    if not segment or field_number >= len(segment):
        return None

    value = segment[field_number]
    return value if value != "" else None


def _hl7_component(
    value: str | None,
    component_number: int,
) -> str | None:
    """Read a 1-based caret-delimited HL7 component."""
    if not value:
        return None

    parts = value.split("^")
    index = component_number - 1

    if index < 0 or index >= len(parts):
        return None

    return parts[index] or None


def _hl7_date_to_fhir(value: str | None) -> str | None:
    """Convert YYYYMMDD or longer HL7 TS text to a FHIR date."""
    if not value or len(value) < 8:
        return None

    date_text = value[:8]
    if not date_text.isdigit():
        return None

    return f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"


def _hl7_gender_to_fhir(value: str | None) -> str | None:
    """Map a small set of common HL7 administrative-sex codes."""
    mapping = {
        "M": "male",
        "F": "female",
        "O": "other",
        "U": "unknown",
        "A": "other",
        "N": "unknown",
    }
    return mapping.get(str(value or "").strip().upper())


def _hl7_patient_class_to_fhir(value: str | None) -> dict[str, Any] | None:
    """Map common PV1-2 patient classes to FHIR encounter class coding."""
    mapping = {
        "I": ("IMP", "inpatient encounter"),
        "O": ("AMB", "ambulatory"),
        "E": ("EMER", "emergency"),
        "P": ("PRENC", "pre-admission"),
    }

    code = str(value or "").strip().upper()
    mapped = mapping.get(code)

    if mapped is None:
        return None

    return {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": mapped[0],
        "display": mapped[1],
    }


@mcp.tool()
@fhir_mcp.tool()
def map_hl7_v2_adt_to_fhir(
    hl7_message: str,
) -> dict[str, Any]:
    """
    Demonstrate a conservative HL7 v2 ADT-to-FHIR mapping.

    Supported demonstration fields include:
      - MSH-9 message type / trigger event
      - PID-3 patient identifier
      - PID-5 patient name
      - PID-7 date of birth
      - PID-8 administrative sex
      - PID-11 address
      - PV1-2 patient class
      - PV1-3 assigned patient location
      - DG1-3 diagnosis code/text

    The output is an educational mapping preview aligned with common
    HL7 v2-to-FHIR mapping patterns. It is NOT a production interface engine
    or a conformance-certified transformation.

    Args:
        hl7_message: Synthetic/demo pipe-delimited HL7 v2 ADT message.
    """
    message = hl7_message.strip()

    if not message:
        return {
            "success": False,
            "error": "An HL7 v2 message is required.",
        }

    if len(message) > HL7_V2_MESSAGE_MAX_CHARACTERS:
        return {
            "success": False,
            "error": (
                "The HL7 v2 message exceeds the configured demonstration "
                "size limit."
            ),
        }

    segments = _split_hl7_v2_segments(message)

    if not segments or segments[0][0] != "MSH":
        return {
            "success": False,
            "error": "The message must begin with an MSH segment.",
        }

    by_name: dict[str, list[list[str]]] = {}
    for segment in segments:
        if not segment:
            continue
        by_name.setdefault(segment[0], []).append(segment)

    msh = by_name.get("MSH", [None])[0]
    pid = by_name.get("PID", [None])[0]
    pv1 = by_name.get("PV1", [None])[0]
    dg1_segments = by_name.get("DG1", [])

    # MSH indexing is special after splitting because MSH-1 is the delimiter.
    message_type_field = msh[8] if msh and len(msh) > 8 else None
    message_code = _hl7_component(message_type_field, 1)
    trigger_event = _hl7_component(message_type_field, 2)

    if message_code and message_code.upper() != "ADT":
        return {
            "success": False,
            "supported_message_family": False,
            "message_type": message_code,
            "trigger_event": trigger_event,
            "error": (
                "This demonstration tool currently supports HL7 v2 ADT "
                "messages only."
            ),
        }

    if pid is None:
        return {
            "success": False,
            "error": "An ADT mapping demonstration requires a PID segment.",
        }

    patient_identifier = _hl7_field(pid, 3)
    patient_name = _hl7_field(pid, 5)
    patient_address = _hl7_field(pid, 11)

    patient_resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": "patient-demo",
    }

    identifier_value = _hl7_component(patient_identifier, 1)
    assigning_authority = _hl7_component(patient_identifier, 4)
    if identifier_value:
        patient_resource["identifier"] = [
            {
                "value": identifier_value,
                "assigner": (
                    {"display": assigning_authority}
                    if assigning_authority
                    else None
                ),
            }
        ]

    family = _hl7_component(patient_name, 1)
    given = _hl7_component(patient_name, 2)
    middle = _hl7_component(patient_name, 3)
    if any((family, given, middle)):
        patient_resource["name"] = [
            {
                "family": family,
                "given": [value for value in (given, middle) if value],
            }
        ]

    birth_date = _hl7_date_to_fhir(_hl7_field(pid, 7))
    if birth_date:
        patient_resource["birthDate"] = birth_date

    gender = _hl7_gender_to_fhir(_hl7_field(pid, 8))
    if gender:
        patient_resource["gender"] = gender

    if patient_address:
        patient_resource["address"] = [
            {
                "line": [
                    value
                    for value in (
                        _hl7_component(patient_address, 1),
                        _hl7_component(patient_address, 2),
                    )
                    if value
                ],
                "city": _hl7_component(patient_address, 3),
                "state": _hl7_component(patient_address, 4),
                "postalCode": _hl7_component(patient_address, 5),
                "country": _hl7_component(patient_address, 6),
            }
        ]

    conceptual_resources: list[dict[str, Any]] = [patient_resource]
    field_mappings: list[dict[str, str]] = [
        {"hl7_v2": "PID-3", "fhir": "Patient.identifier"},
        {"hl7_v2": "PID-5", "fhir": "Patient.name"},
        {"hl7_v2": "PID-7", "fhir": "Patient.birthDate"},
        {"hl7_v2": "PID-8", "fhir": "Patient.gender"},
        {"hl7_v2": "PID-11", "fhir": "Patient.address"},
    ]

    if pv1 is not None:
        encounter: dict[str, Any] = {
            "resourceType": "Encounter",
            "id": "encounter-demo",
            "subject": {"reference": "Patient/patient-demo"},
        }

        encounter_class = _hl7_patient_class_to_fhir(
            _hl7_field(pv1, 2)
        )
        if encounter_class:
            encounter["class"] = encounter_class

        assigned_location = _hl7_field(pv1, 3)
        if assigned_location:
            location_display = "^".join(
                value
                for value in assigned_location.split("^")
                if value
            )
            encounter["location"] = [
                {
                    "location": {
                        "display": location_display,
                    }
                }
            ]

        encounter_status_by_event = {
            "A01": "in-progress",
            "A03": "finished",
            "A04": "in-progress",
            "A08": "in-progress",
        }
        encounter["status"] = encounter_status_by_event.get(
            str(trigger_event or "").upper(),
            "unknown",
        )

        conceptual_resources.append(encounter)
        field_mappings.extend(
            [
                {"hl7_v2": "PV1-2", "fhir": "Encounter.class"},
                {"hl7_v2": "PV1-3", "fhir": "Encounter.location"},
            ]
        )

    condition_resources: list[dict[str, Any]] = []

    for index, dg1 in enumerate(dg1_segments, start=1):
        diagnosis = _hl7_field(dg1, 3)
        code = _hl7_component(diagnosis, 1)
        display = _hl7_component(diagnosis, 2)
        system = _hl7_component(diagnosis, 3)

        if not any((code, display)):
            continue

        condition = {
            "resourceType": "Condition",
            "id": f"condition-demo-{index}",
            "subject": {"reference": "Patient/patient-demo"},
            "code": {
                "coding": [
                    {
                        "system": system,
                        "code": code,
                        "display": display,
                    }
                ],
                "text": display or code,
            },
        }

        condition_resources.append(condition)

    if condition_resources:
        conceptual_resources.extend(condition_resources)
        field_mappings.append(
            {"hl7_v2": "DG1-3", "fhir": "Condition.code"}
        )

    return {
        "success": True,
        "mapping_status": "EDUCATIONAL_DEMONSTRATION",
        "source_standard": "HL7 Version 2",
        "target_standard": f"HL7 FHIR {HL7_V2_MAPPING_FHIR_VERSION}",
        "message_type": message_code or "ADT",
        "trigger_event": trigger_event,
        "segments_detected": sorted(by_name.keys()),
        "field_mappings": field_mappings,
        "conceptual_fhir_resources": conceptual_resources,
        "resource_types_created": [
            resource.get("resourceType")
            for resource in conceptual_resources
        ],
        "important_notice": (
            "This is a limited interoperability demonstration using a "
            "synthetic/demo HL7 v2 message. It is not a complete HL7 v2-to-"
            "FHIR implementation, interface-engine replacement, profile "
            "validator, or production EHR integration. Real implementations "
            "require version-specific mappings, terminology handling, local "
            "profiles, validation, and organizational interface agreements."
        ),
    }

@mcp.tool()
@fhir_mcp.tool()
def validate_patient_fhir_bundle(
    patient_filename: str,
    maximum_conditions: int = 25,
    maximum_medications: int = 25,
    maximum_observations: int = 25,
) -> dict[str, Any]:
    """
    Validate and summarize one synthetic Synthea HL7 FHIR patient Bundle.

    The patient JSON file must already exist in the server's data/synthea
    directory. This tool is intentionally generic and is not hard-coded to a
    specific patient.

    Use this tool before patient-to-trial screening to extract a compact,
    structured patient profile from a large Synthea FHIR Bundle.

    Args:
        patient_filename: JSON filename stored in data/synthea.
        maximum_conditions: Maximum active conditions to return, from 1 to 50.
        maximum_medications: Maximum active medications to return, from 1 to 50.
        maximum_observations: Maximum latest observations to return, from 1 to 50.
    """
    maximum_conditions = max(1, min(maximum_conditions, MAX_PATIENT_SUMMARY_ITEMS))
    maximum_medications = max(1, min(maximum_medications, MAX_PATIENT_SUMMARY_ITEMS))
    maximum_observations = max(1, min(maximum_observations, MAX_PATIENT_SUMMARY_ITEMS))

    bundle, error, resolved_filename = _load_synthea_patient_bundle(
    patient_filename
    )

    if error is not None or bundle is None:
        return {
            "success": False,
            "error": error or "Unable to load the patient FHIR Bundle.",
        }

    result = _extract_patient_fhir_summary(
        bundle=bundle,
        maximum_conditions=maximum_conditions,
        maximum_medications=maximum_medications,
        maximum_observations=maximum_observations,
    )

    if result.get("success"):
        result["source"] = "MITRE Synthea synthetic HL7 FHIR patient data"
        result["patient_filename"] = resolved_filename
        result["requested_patient_reference"] = patient_filename

    return result


@mcp.tool()
@fhir_mcp.tool()
async def screen_patient_against_trial(
    patient_filename: str,
    nct_id: str,
    target_condition: str = "",
) -> dict[str, Any]:
    """
    Perform conservative preliminary screening of one synthetic FHIR patient
    against one ClinicalTrials.gov study.

    This tool automatically compares only facts that can be determined
    conservatively from the supported data: age, sex, and direct Condition
    matches. When target_condition is supplied, TrialScout also evaluates that
    exact discovery condition separately so another condition listed by a
    multi-condition trial cannot satisfy the target-condition evidence gate.
    Other structured eligibility requirements remain UNKNOWN and require human
    review. The tool never declares a patient eligible or ineligible.

    Args:
        patient_filename: JSON filename stored in data/synthea.
        nct_id: ClinicalTrials.gov identifier, such as "NCT07064473".
        target_condition: Optional exact condition that caused this trial to
            enter the discovery set, such as "Type 2 diabetes". When supplied,
            this condition is evaluated separately for ranking semantics.
    """
    normalized_nct_id = nct_id.strip().upper()
    target_condition = target_condition.strip()

    if (
        not normalized_nct_id.startswith("NCT")
        or len(normalized_nct_id) != 11
        or not normalized_nct_id[3:].isdigit()
    ):
        return {
            "success": False,
            "error": (
                "A valid NCT identifier is required, for example "
                "NCT07064473."
            ),
        }

    patient_bundle, patient_error, resolved_filename = (
    _load_synthea_patient_bundle(patient_filename)
    )
    if patient_error is not None or patient_bundle is None:
        return {
            "success": False,
            "error": patient_error or "Unable to load the patient FHIR Bundle.",
        }

    patient_summary = _extract_patient_fhir_summary(
        bundle=patient_bundle,
        maximum_conditions=MAX_PATIENT_SUMMARY_ITEMS,
        maximum_medications=MAX_PATIENT_SUMMARY_ITEMS,
        maximum_observations=MAX_PATIENT_SUMMARY_ITEMS,
    )
    if not patient_summary.get("success"):
        return patient_summary

    patient_resources = _flatten_fhir_resources(patient_bundle)
    condition_inventory = _extract_patient_condition_inventory(patient_resources)

    trial_payload, trial_error = await _fetch_trial_for_screening(normalized_nct_id)
    if trial_error is not None or trial_payload is None:
        return {
            "success": False,
            "error": trial_error or "Unable to retrieve the trial.",
        }

    protocol = trial_payload.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    eligibility = protocol.get("eligibilityModule", {})

    trial_conditions = conditions_module.get("conditions", [])
    if not isinstance(trial_conditions, list):
        trial_conditions = []

    minimum_age_text = eligibility.get("minimumAge")
    maximum_age_text = eligibility.get("maximumAge")
    minimum_age_years = _parse_age_years(minimum_age_text)
    maximum_age_years = _parse_age_years(maximum_age_text)

    patient_info = patient_summary.get("patient", {})
    patient_age = patient_info.get("age_years")
    patient_gender = str(patient_info.get("gender") or "").casefold()

    matched_facts: list[dict[str, Any]] = []
    possible_conflicts: list[dict[str, Any]] = []
    unknown_requirements: list[dict[str, Any]] = []

    # Age comparison.
    if isinstance(patient_age, int):
        age_matches = True
        if minimum_age_years is not None and patient_age < minimum_age_years:
            age_matches = False
        if maximum_age_years is not None and patient_age > maximum_age_years:
            age_matches = False

        age_result = {
            "criterion_type": "age",
            "patient_value": patient_age,
            "trial_minimum_age": minimum_age_text,
            "trial_maximum_age": maximum_age_text,
        }

        if age_matches:
            matched_facts.append({
                **age_result,
                "classification": "MATCH",
                "reason": (
                    "The published trial age range includes the patient's "
                    "current age."
                ),
            })
        else:
            possible_conflicts.append({
                **age_result,
                "classification": "POSSIBLE_CONFLICT",
                "reason": (
                    "The patient's current age falls outside the published "
                    "trial age range."
                ),
            })
    else:
        unknown_requirements.append({
            "criterion_type": "age",
            "classification": "UNKNOWN",
            "reason": (
                "Patient age could not be calculated from the FHIR Patient "
                "resource."
            ),
        })

    # Sex comparison.
    trial_sex = str(eligibility.get("sex") or "").upper()
    if trial_sex in {"ALL", ""}:
        matched_facts.append({
            "criterion_type": "sex",
            "patient_value": patient_info.get("gender"),
            "trial_value": trial_sex or None,
            "classification": "MATCH",
            "reason": (
                "The published trial record does not restrict enrollment to "
                "a different sex."
            ),
        })
    elif patient_gender in {"male", "female"}:
        if patient_gender == trial_sex.casefold():
            matched_facts.append({
                "criterion_type": "sex",
                "patient_value": patient_info.get("gender"),
                "trial_value": trial_sex,
                "classification": "MATCH",
                "reason": (
                    "The FHIR Patient gender matches the published trial sex "
                    "restriction."
                ),
            })
        else:
            possible_conflicts.append({
                "criterion_type": "sex",
                "patient_value": patient_info.get("gender"),
                "trial_value": trial_sex,
                "classification": "POSSIBLE_CONFLICT",
                "reason": (
                    "The FHIR Patient gender does not match the published "
                    "trial sex restriction."
                ),
            })
    else:
        unknown_requirements.append({
            "criterion_type": "sex",
            "patient_value": patient_info.get("gender"),
            "trial_value": trial_sex,
            "classification": "UNKNOWN",
            "reason": (
                "The patient's FHIR gender could not be deterministically "
                "compared with the trial restriction."
            ),
        })

    # Condition comparison.
    patient_conditions = (
        condition_inventory["active"] + condition_inventory["historical"]
    )

    # Preserve the discovery target as a distinct ranking signal. This avoids
    # allowing an unrelated co-listed trial condition to satisfy the ranking
    # condition gate.
    target_condition_evidence = _evaluate_target_condition_evidence(
        patient_conditions=patient_conditions,
        trial_conditions=trial_conditions,
        target_condition=target_condition,
    )

    # Continue evaluating all registered trial conditions for screening
    # transparency. The alignment assessment will use target_condition_evidence
    # when a target condition was explicitly supplied.
    for trial_condition in trial_conditions:
        if not isinstance(trial_condition, str):
            continue

        matching_patient_conditions = [
            condition
            for condition in patient_conditions
            if _clinical_text_matches(
                trial_condition,
                str(condition.get("name") or ""),
            )
        ]

        if matching_patient_conditions:
            active_matches = [
                condition
                for condition in matching_patient_conditions
                if condition.get("clinical_status") == "active"
            ]
            matched_facts.append({
                "criterion_type": "condition",
                "trial_condition": trial_condition,
                "classification": "MATCH",
                "patient_matches": matching_patient_conditions[:5],
                "active_match_found": bool(active_matches),
                "reason": (
                    "A matching FHIR Condition record was found in the "
                    "synthetic patient bundle. This confirms only that the "
                    "condition is represented in the record, not that all "
                    "trial-specific disease criteria are met."
                ),
            })
        else:
            possible_conflicts.append({
                "criterion_type": "condition",
                "trial_condition": trial_condition,
                "classification": "POSSIBLE_CONFLICT",
                "reason": (
                    "No matching FHIR Condition was found in the supported "
                    "patient record. This may reflect either a true mismatch "
                    "or incomplete patient data."
                ),
            })

    # Structured FHIR eligibility is retrieved for transparency. Arbitrary
    # medical criteria remain UNKNOWN rather than being guessed.
    trial_fhir_bundle, fhir_error = await _fetch_trial_fhir_for_screening(
        normalized_nct_id
    )
    structured_eligibility = None
    fhir_resource_counts = None

    if trial_fhir_bundle is not None:
        trial_fhir_resources = _flatten_fhir_resources(trial_fhir_bundle)
        fhir_resource_counts = _count_fhir_resources(trial_fhir_resources)
        structured_eligibility = _extract_fhir_eligibility_group(
            trial_fhir_resources,
            normalized_nct_id,
        )
        unknown_requirements.extend(
            _summarize_unknown_structured_criteria(
                structured_eligibility,
                maximum_items=None,
                trial_minimum_age=minimum_age_text,
                trial_maximum_age=maximum_age_text,
            )
        )
    elif fhir_error:
        unknown_requirements.append({
            "criterion_type": "structured_fhir_eligibility",
            "classification": "UNKNOWN",
            "reason": fhir_error,
        })

    return {
        "success": True,
        "screening_status": "REQUIRES_HUMAN_REVIEW",
        "screening_scope": (
            "Conservative preliminary screening using synthetic patient FHIR "
            "data and official ClinicalTrials.gov study data."
        ),
        "target_condition": target_condition or None,
        "target_condition_evidence": target_condition_evidence,
        "patient": {
            "filename": resolved_filename,
            "requested_patient_reference": patient_filename,
            "fhir_resource_id": patient_info.get("fhir_resource_id"),
            "name": patient_info.get("name"),
            "gender": patient_info.get("gender"),
            "birth_date": patient_info.get("birth_date"),
            "age_years": patient_info.get("age_years"),
            "location": patient_info.get("location"),
            "active_condition_count": len(condition_inventory["active"]),
            "historical_condition_count": len(condition_inventory["historical"]),
        },
        "trial": {
            "nct_id": identification.get("nctId") or normalized_nct_id,
            "brief_title": identification.get("briefTitle"),
            "official_title": identification.get("officialTitle"),
            "overall_status": status_module.get("overallStatus"),
            "conditions": trial_conditions,
            "requested_target_condition": target_condition or None,
            "minimum_age": minimum_age_text,
            "maximum_age": maximum_age_text,
            "sex": eligibility.get("sex"),
            "clinicaltrials_url": (
                f"https://clinicaltrials.gov/study/{normalized_nct_id}"
            ),
        },
        "result_counts": {
            "matched_facts": len(matched_facts),
            "possible_conflicts": len(possible_conflicts),
            "unknown_requirements": len(unknown_requirements),
        },
        "matched_facts": matched_facts,
        "possible_conflicts": possible_conflicts,
        "unknown_requirements": unknown_requirements[
            :UNKNOWN_REQUIREMENT_PREVIEW_LIMIT
        ],
        "unknown_requirement_preview_count": min(
            len(unknown_requirements),
            UNKNOWN_REQUIREMENT_PREVIEW_LIMIT,
        ),
        "unknown_requirements_truncated": (
            len(unknown_requirements) > UNKNOWN_REQUIREMENT_PREVIEW_LIMIT
        ),
        "trial_fhir": {
            "structured_eligibility_available": structured_eligibility is not None,
            "structured_eligibility_characteristic_count": (
                structured_eligibility.get("characteristic_count")
                if isinstance(structured_eligibility, dict)
                else None
            ),
            "resource_counts": fhir_resource_counts,
        },
        "methodology_note": (
            "TrialScout automatically evaluates age, sex, and direct "
            "condition matches. When a target condition is supplied, it is "
            "evaluated separately from other trial conditions for ranking. "
            "It does not automatically interpret arbitrary "
            "medication exclusions, laboratory thresholds, procedures, "
            "disease severity, timing rules, pregnancy criteria, or other "
            "complex eligibility logic. Those remain UNKNOWN."
        ),
        "important_notice": (
            "This is research software using synthetic patient data. MATCH "
            "does not mean eligible, POSSIBLE_CONFLICT does not mean "
            "ineligible, and UNKNOWN does not mean the criterion is absent. "
            "Final eligibility must be determined by the official study team."
        ),
    }


@mcp.tool()
@matching_mcp.tool()

async def assess_trial_alignment(
    patient_filename: str,
    nct_id: str,
    target_condition: str = "",
) -> dict[str, Any]:
    """
    Assess preliminary qualitative alignment between one synthetic Synthea
    FHIR patient and one ClinicalTrials.gov study.

    No numerical compatibility score is produced. The assessment reports:
      - target/registered-condition evidence
      - FULL / PARTIAL / NONE / UNKNOWN condition evidence
      - age alignment
      - recruitment status
      - sex alignment when applicable
      - unresolved eligibility requirements
      - a qualitative supported-alignment band

    Args:
        patient_filename: Synthetic patient name or exact filename.
        nct_id: ClinicalTrials.gov identifier.
        target_condition: Optional exact discovery condition. When supplied,
            it controls the condition gate and cannot be substituted by a
            different co-listed trial condition.
    """
    screening = await screen_patient_against_trial(
        patient_filename=patient_filename,
        nct_id=nct_id,
        target_condition=target_condition,
    )

    if not screening.get("success"):
        return {
            "success": False,
            "error": screening.get(
                "error",
                "Unable to complete patient-to-trial screening.",
            ),
        }

    assessment = _build_preliminary_alignment_assessment(screening)

    return {
        "success": True,
        "assessment_status": "REQUIRES_HUMAN_REVIEW",
        "patient": screening.get("patient"),
        "trial": screening.get("trial"),
        "target_condition": screening.get("target_condition"),
        "target_condition_evidence": screening.get(
            "target_condition_evidence"
        ),
        "assessment": assessment,
        "screening_result_counts": screening.get("result_counts"),
        "possible_conflicts": screening.get("possible_conflicts", []),
        "unknown_requirements": screening.get("unknown_requirements", []),
        "unknown_requirement_count": (
            screening.get("result_counts", {}).get("unknown_requirements")
        ),
        "unknown_requirements_truncated": screening.get(
            "unknown_requirements_truncated",
            False,
        ),
        "structured_trial_fhir_available": (
            screening.get("trial_fhir", {}).get(
                "structured_eligibility_available"
            )
        ),
        "clinicaltrials_url": (
            screening.get("trial", {}).get("clinicaltrials_url")
        ),
        "important_notice": (
            "This qualitative alignment assessment is for research assistance "
            "only. It does not establish eligibility or ineligibility, and it "
            "does not recommend enrollment. Final eligibility must be "
            "determined by the official study team."
        ),
    }


@mcp.tool()
async def calculate_compatibility_score(
    patient_filename: str,
    nct_id: str,
    target_condition: str = "",
) -> dict[str, Any]:
    """
    Deprecated legacy wrapper.

    Numerical compatibility scoring has been removed. This legacy tool name
    remains temporarily on the shared /mcp endpoint so older Agent Studio
    configurations fail gracefully while migrating to assess_trial_alignment.
    """
    result = await assess_trial_alignment(
        patient_filename=patient_filename,
        nct_id=nct_id,
        target_condition=target_condition,
    )

    if result.get("success"):
        result["deprecated_tool_name"] = True
        result["migration_note"] = (
            "Use assess_trial_alignment. Numerical compatibility scoring was "
            "removed in favor of qualitative deterministic alignment."
        )

    return result



@mcp.tool()
@matching_mcp.tool()
async def compare_clinical_trials(
    nct_ids: list[str],
    location_filter: str = "",
    maximum_locations_per_trial: int = 3,
) -> dict[str, Any]:
    """
    Compare 2 to 5 ClinicalTrials.gov studies side-by-side using official
    structured study records.

    This tool is for factual comparison only. It does not rank trials,
    recommend a study, or determine patient eligibility.

    Args:
        nct_ids: List of 2 to 5 ClinicalTrials.gov identifiers.
        location_filter: Optional city, state, region, or country. When
            supplied, comparison locations are limited to matching sites.
        maximum_locations_per_trial: Maximum matching locations to return for
            each trial, from 1 to 10.
    """
    if not isinstance(nct_ids, list):
        return {
            "success": False,
            "error": "nct_ids must be a list of 2 to 5 NCT identifiers.",
        }

    normalized_ids: list[str] = []

    for value in nct_ids:
        if not isinstance(value, str):
            continue

        normalized = value.strip().upper()

        if normalized and normalized not in normalized_ids:
            normalized_ids.append(normalized)

    if len(normalized_ids) < 2:
        return {
            "success": False,
            "error": (
                "At least 2 unique NCT identifiers are required for "
                "comparison."
            ),
        }

    if len(normalized_ids) > MAX_TRIALS_PER_COMPARISON:
        return {
            "success": False,
            "error": f"A maximum of {MAX_TRIALS_PER_COMPARISON} clinical trials can be compared at once.",
        }

    location_filter = location_filter.strip()
    maximum_locations_per_trial = max(
        1,
        min(int(maximum_locations_per_trial), 10),
    )

    compared_trials: list[dict[str, Any]] = []
    trial_errors: list[dict[str, Any]] = []

    for nct_id in normalized_ids:
        details = await get_trial_details(
            nct_id=nct_id,
            location_filter=location_filter,
            maximum_locations=maximum_locations_per_trial,
        )

        if not details.get("success"):
            trial_errors.append(
                {
                    "nct_id": nct_id,
                    "error": details.get(
                        "error",
                        "Unable to retrieve this clinical trial.",
                    ),
                }
            )
            continue

        organization = details.get("organization")
        if isinstance(organization, dict):
            sponsor_name = (
                organization.get("fullName")
                or organization.get("name")
                or organization.get("class")
            )
        else:
            sponsor_name = organization

        enrollment = details.get("enrollment")
        if not isinstance(enrollment, dict):
            enrollment = {}

        interventions: list[dict[str, Any]] = []
        for intervention in details.get("interventions", []):
            if not isinstance(intervention, dict):
                continue

            interventions.append(
                {
                    "type": intervention.get("type"),
                    "name": intervention.get("name"),
                    "arm_group_labels": intervention.get(
                        "armGroupLabels",
                        [],
                    ),
                    "description": _shorten_text(
                        intervention.get("description"),
                        maximum_length=500,
                    ),
                }
            )

            if len(interventions) >= COMPARISON_INTERVENTION_PREVIEW_LIMIT:
                break

        compared_trials.append(
            {
                "nct_id": details.get("nct_id") or nct_id,
                "brief_title": details.get("brief_title"),
                "official_title": details.get("official_title"),
                "sponsor": sponsor_name,
                "overall_status": details.get("overall_status"),
                "study_type": details.get("study_type"),
                "phases": details.get("phases", []),
                "conditions": details.get("conditions", []),
                "interventions": interventions,
                "minimum_age": details.get("minimum_age"),
                "maximum_age": details.get("maximum_age"),
                "sex": details.get("sex"),
                "healthy_volunteers": details.get("healthy_volunteers"),
                "enrollment": {
                    "count": enrollment.get("count"),
                    "type": enrollment.get("type"),
                },
                "start_date": details.get("start_date"),
                "completion_date": details.get("completion_date"),
                "eligibility_summary": _shorten_text(
                    details.get("eligibility_criteria"),
                    maximum_length=1200,
                ),
                "requested_location_filter": (
                    details.get("requested_location_filter")
                ),
                "returned_location_count": details.get(
                    "returned_location_count"
                ),
                "locations": details.get("locations", []),
                "clinicaltrials_url": details.get("clinicaltrials_url"),
            }
        )

    if len(compared_trials) < 2:
        return {
            "success": False,
            "error": (
                "Fewer than 2 valid clinical trials could be retrieved, so "
                "a comparison could not be completed."
            ),
            "requested_nct_ids": normalized_ids,
            "trial_errors": trial_errors,
        }

    # Build compact dimension arrays so an agent can present a deterministic
    # side-by-side comparison without re-parsing large trial records.
    comparison_dimensions = {
        "recruitment_status": [
            {
                "nct_id": trial.get("nct_id"),
                "value": trial.get("overall_status"),
            }
            for trial in compared_trials
        ],
        "study_type": [
            {
                "nct_id": trial.get("nct_id"),
                "value": trial.get("study_type"),
            }
            for trial in compared_trials
        ],
        "phase": [
            {
                "nct_id": trial.get("nct_id"),
                "value": trial.get("phases"),
            }
            for trial in compared_trials
        ],
        "age_range": [
            {
                "nct_id": trial.get("nct_id"),
                "minimum_age": trial.get("minimum_age"),
                "maximum_age": trial.get("maximum_age"),
            }
            for trial in compared_trials
        ],
        "sex": [
            {
                "nct_id": trial.get("nct_id"),
                "value": trial.get("sex"),
            }
            for trial in compared_trials
        ],
        "enrollment": [
            {
                "nct_id": trial.get("nct_id"),
                "value": trial.get("enrollment"),
            }
            for trial in compared_trials
        ],
        "conditions": [
            {
                "nct_id": trial.get("nct_id"),
                "value": trial.get("conditions"),
            }
            for trial in compared_trials
        ],
        "interventions": [
            {
                "nct_id": trial.get("nct_id"),
                "value": [
                    {
                        "type": intervention.get("type"),
                        "name": intervention.get("name"),
                    }
                    for intervention in trial.get("interventions", [])
                ],
            }
            for trial in compared_trials
        ],
        "locations": [
            {
                "nct_id": trial.get("nct_id"),
                "returned_location_count": trial.get(
                    "returned_location_count"
                ),
                "value": trial.get("locations"),
            }
            for trial in compared_trials
        ],
    }

    return {
        "success": True,
        "source": "ClinicalTrials.gov API v2",
        "comparison_status": "FACTUAL_COMPARISON_ONLY",
        "requested_nct_ids": normalized_ids,
        "compared_trial_count": len(compared_trials),
        "requested_location_filter": location_filter or None,
        "trials": compared_trials,
        "comparison_dimensions": comparison_dimensions,
        "trial_errors": trial_errors,
        "important_notice": (
            "This tool compares published study facts only. It does not rank "
            "trials, recommend a study, or establish patient eligibility. "
            "Eligibility must be confirmed by the official study team."
        ),
    }


@mcp.tool()
@matching_mcp.tool()

async def rank_trials_for_patient(
    patient_filename: str,
    nct_ids: list[str],
    target_condition: str = "",
) -> dict[str, Any]:
    """
    Rank 2 to configured-maximum ClinicalTrials.gov studies for one synthetic
    Synthea FHIR patient using qualitative deterministic evidence.

    No numerical compatibility score is used.

    Ranking priority:
      1. Target/condition evidence gate.
      2. Current recruiting status.
      3. Fewer deterministic age/sex conflicts.
      4. Condition evidence FULL > PARTIAL > NONE > UNKNOWN.
      5. More supported basic-fact matches.
      6. NCT identifier as a stable tie-breaker.

    UNKNOWN complex eligibility criteria are surfaced for human review but are
    not treated as negative evidence merely because one study has more
    structured criteria than another.

    Args:
        patient_filename: Synthetic patient name or JSON filename.
        nct_ids: List of known ClinicalTrials.gov identifiers.
        target_condition: Optional exact discovery condition. When supplied,
            another co-listed trial condition cannot satisfy this gate.
    """
    if not isinstance(nct_ids, list):
        return {
            "success": False,
            "error": "nct_ids must be a list of NCT identifiers.",
        }

    target_condition = target_condition.strip()

    normalized_ids: list[str] = []
    for value in nct_ids:
        if not isinstance(value, str):
            continue

        normalized = value.strip().upper()
        if normalized and normalized not in normalized_ids:
            normalized_ids.append(normalized)

    if len(normalized_ids) < 2:
        return {
            "success": False,
            "error": (
                "At least 2 unique NCT identifiers are required for ranking."
            ),
        }

    if len(normalized_ids) > MAX_TRIALS_PER_RANKING:
        return {
            "success": False,
            "error": (
                "A maximum of "
                f"{MAX_TRIALS_PER_RANKING} clinical trials can be ranked "
                "at once."
            ),
        }

    ranking_candidates: list[dict[str, Any]] = []
    trial_errors: list[dict[str, Any]] = []
    resolved_patient: dict[str, Any] | None = None

    for nct_id in normalized_ids:
        result = await assess_trial_alignment(
            patient_filename=patient_filename,
            nct_id=nct_id,
            target_condition=target_condition,
        )

        if not result.get("success"):
            trial_errors.append(
                {
                    "nct_id": nct_id,
                    "error": result.get(
                        "error",
                        "Unable to assess preliminary alignment.",
                    ),
                }
            )
            continue

        if resolved_patient is None:
            resolved_patient = result.get("patient")

        trial = result.get("trial", {})
        assessment = result.get("assessment", {})
        condition = assessment.get("condition_evidence", {})
        dimensions = assessment.get("dimensions", [])

        recruitment_status = "UNKNOWN"
        for dimension in dimensions:
            if (
                isinstance(dimension, dict)
                and dimension.get("dimension") == "recruitment_status"
            ):
                recruitment_status = str(
                    dimension.get("classification") or "UNKNOWN"
                )
                break

        explicit_conflicts = assessment.get("explicit_conflicts", [])
        supported_matches = assessment.get("supported_matches", [])

        ranking_candidates.append(
            {
                "nct_id": trial.get("nct_id") or nct_id,
                "brief_title": trial.get("brief_title"),
                "overall_status": trial.get("overall_status"),
                "conditions": trial.get("conditions", []),
                "minimum_age": trial.get("minimum_age"),
                "maximum_age": trial.get("maximum_age"),
                "sex": trial.get("sex"),
                "target_condition": condition.get("target_condition"),
                "target_condition_status": condition.get(
                    "target_condition_status"
                ),
                "condition_match_scope": condition.get("scope"),
                "condition_evidence_level": condition.get("level"),
                "condition_gate_triggered": condition.get("gate_triggered"),
                "registered_condition_evidence": condition.get(
                    "registered_condition_evidence"
                ),
                "alignment_band": assessment.get("alignment_band"),
                "evidence_scope": assessment.get("evidence_scope"),
                "unresolved_eligibility_present": assessment.get(
                    "unresolved_eligibility_present"
                ),
                "unknown_requirement_count": assessment.get(
                    "unknown_requirement_count"
                ),
                "recruitment_status": recruitment_status,
                "explicit_conflicts": explicit_conflicts,
                "explicit_conflict_count": len(explicit_conflicts),
                "supported_matches": supported_matches,
                "supported_match_count": len(supported_matches),
                "supported_unknowns": assessment.get(
                    "supported_unknowns",
                    [],
                ),
                "dimensions": dimensions,
                "clinicaltrials_url": result.get("clinicaltrials_url"),
            }
        )

    if len(ranking_candidates) < 2:
        return {
            "success": False,
            "error": (
                "Fewer than 2 trials could be assessed successfully, so a "
                "patient-specific ranking could not be completed."
            ),
            "patient_reference": patient_filename,
            "requested_nct_ids": normalized_ids,
            "trial_errors": trial_errors,
        }

    ranking_candidates.sort(key=_alignment_ranking_key)

    ranked_trials: list[dict[str, Any]] = []

    for index, item in enumerate(ranking_candidates, start=1):
        condition_level = item.get("condition_evidence_level")
        gate_triggered = item.get("condition_gate_triggered") is True

        if target_condition and gate_triggered:
            ranking_explanation = (
                f"Direct patient Condition evidence for the requested target "
                f"condition '{target_condition}' was not found. A different "
                "condition listed by the study cannot satisfy that gate, so "
                "the supported alignment is limited."
            )
        elif condition_level == "PARTIAL":
            ranking_explanation = (
                "The patient has direct Condition evidence for some, but not "
                "all, registered study conditions. The ranking therefore "
                "treats condition evidence as partial."
            )
        elif condition_level == "FULL":
            ranking_explanation = (
                "Direct Condition evidence aligns with the applicable "
                "registered condition scope. Ordering then considers current "
                "recruitment, deterministic age/sex conflicts, and other "
                "supported basic-fact evidence."
            )
        elif condition_level == "NONE":
            ranking_explanation = (
                "No direct patient Condition evidence was found for the "
                "applicable registered condition scope, limiting the "
                "supported alignment."
            )
        else:
            ranking_explanation = (
                "Condition evidence could not be resolved deterministically, "
                "so the ranking remains conservative."
            )

        ranked_trials.append(
            {
                "rank": index,
                **item,
                "ranking_explanation": ranking_explanation,
            }
        )

    top_ranked = ranked_trials[0]

    return {
        "success": True,
        "ranking_status": "QUALITATIVE_PRELIMINARY_ALIGNMENT_RANKING",
        "review_status": "REQUIRES_HUMAN_REVIEW",
        "patient_reference": patient_filename,
        "requested_target_condition": target_condition or None,
        "patient": resolved_patient,
        "requested_nct_ids": normalized_ids,
        "ranked_trial_count": len(ranked_trials),
        "ranked_trials": ranked_trials,
        "top_preliminary_alignment": {
            "nct_id": top_ranked.get("nct_id"),
            "brief_title": top_ranked.get("brief_title"),
            "alignment_band": top_ranked.get("alignment_band"),
            "condition_evidence_level": top_ranked.get(
                "condition_evidence_level"
            ),
            "condition_gate_triggered": top_ranked.get(
                "condition_gate_triggered"
            ),
            "evidence_scope": top_ranked.get("evidence_scope"),
        },
        "ranking_methodology": {
            "priority_order": [
                (
                    f"Requested target-condition gate: {target_condition}"
                    if target_condition
                    else "Registered-condition evidence gate"
                ),
                "Currently recruiting status",
                "Fewer deterministic age/sex conflicts",
                "Condition evidence: FULL > PARTIAL > NONE > UNKNOWN",
                "More supported basic-fact matches",
                "NCT identifier stable tie-breaker",
            ],
            "numerical_score_used": False,
            "unknown_requirements_used_as_negative_ranking_weight": False,
            "interpretation": (
                "The ranking uses only qualitative deterministic evidence "
                "supported by TrialScout. Complex eligibility requirements "
                "remain for human review and are not converted into fake "
                "probabilities or point scores."
            ),
        },
        "trial_errors": trial_errors,
        "important_notice": (
            "Rank #1 means strongest supported preliminary alignment among "
            "the evaluated trials under TrialScout's deterministic rules. It "
            "does not mean the patient is eligible, that the trial is "
            "clinically preferable, or that enrollment is recommended."
        ),
    }



@mcp.tool()
@fhir_mcp.tool()
@matching_mcp.tool()
def list_demo_patients(
    name_query: str = "",
    maximum_results: int = 20,
) -> dict[str, Any]:
    """
    List synthetic Synthea FHIR patients available to TrialScout.

    Use this tool before patient validation or screening when the user refers
    to a demo patient by a human-readable name such as "Lou" or "Brook"
    instead of supplying the exact JSON filename.

    Args:
        name_query: Optional case-insensitive name or filename fragment used
            to narrow the available demo patients.
        maximum_results: Maximum number of matching patients to return.
    """
    maximum_results = max(1, min(int(maximum_results), MAX_DEMO_PATIENT_RESULTS))
    query = name_query.strip().casefold()

    if not PATIENT_DATA_DIR.exists():
        return {
            "success": False,
            "error": (
                "The synthetic patient data directory does not exist: "
                f"{PATIENT_DATA_DIR}"
            ),
        }

    patient_files = sorted(PATIENT_DATA_DIR.glob("*.json"))
    patients: list[dict[str, Any]] = []
    unreadable_files: list[str] = []

    for patient_path in patient_files:
        try:
            with patient_path.open("r", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except (OSError, json.JSONDecodeError):
            unreadable_files.append(patient_path.name)
            continue

        if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
            unreadable_files.append(patient_path.name)
            continue

        patient_resource = None

        for entry in bundle.get("entry", []):
            if not isinstance(entry, dict):
                continue

            resource = entry.get("resource")
            if (
                isinstance(resource, dict)
                and resource.get("resourceType") == "Patient"
            ):
                patient_resource = resource
                break

        if patient_resource is None:
            unreadable_files.append(patient_path.name)
            continue

        name = _fhir_patient_name(patient_resource)
        birth_date = patient_resource.get("birthDate")
        age_years = (
            _calculate_age(birth_date)
            if isinstance(birth_date, str)
            else None
        )
        location = _fhir_patient_location(patient_resource)

        searchable_text = " ".join(
            [
                patient_path.name,
                str(name or ""),
                str(patient_resource.get("id") or ""),
                str(location.get("city") or ""),
                str(location.get("state") or ""),
            ]
        ).casefold()

        if query and query not in searchable_text:
            continue

        patients.append(
            {
                "patient_filename": patient_path.name,
                "fhir_resource_id": patient_resource.get("id"),
                "name": name,
                "gender": patient_resource.get("gender"),
                "birth_date": birth_date,
                "age_years": age_years,
                "location": location,
                "source": "MITRE Synthea synthetic HL7 FHIR patient data",
            }
        )

        if len(patients) >= maximum_results:
            break

    return {
        "success": True,
        "name_query": name_query or None,
        "available_patient_file_count": len(patient_files),
        "matching_patient_count": len(patients),
        "patients": patients,
        "unreadable_file_count": len(unreadable_files),
        "note": (
            "These are synthetic Synthea demo patients for research and "
            "software testing. Use the returned patient_filename exactly "
            "when calling validate_patient_fhir_bundle or "
            "screen_patient_against_trial."
        ),
    }



# ---------------------------------------------------------------------------
# Multi-endpoint MCP hosting
# ---------------------------------------------------------------------------
#
# Role-isolated endpoints:
#   /mcp/discovery -> health_check, geocode_location, search_clinical_trials
#   /mcp/analysis  -> health_check, get_trial_details, get_trial_fhir,
#                     get_trial_contact_next_steps
#   /mcp/fhir      -> health_check, map_hl7_v2_adt_to_fhir,
#                     validate_patient_fhir_bundle,
#                     screen_patient_against_trial, list_demo_patients
#   /mcp/matching  -> health_check, assess_trial_alignment,
#                     compare_clinical_trials, rank_trials_for_patient,
#                     list_demo_patients
#
# Temporary backward-compatible endpoint:
#   /mcp           -> all existing tools
#
# Remove the legacy endpoint later, after every Agent Studio specialist has
# been migrated to its role-specific endpoint.


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    """Run all MCP Streamable HTTP session managers in one ASGI process."""
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(discovery_mcp.session_manager.run())
        await stack.enter_async_context(analysis_mcp.session_manager.run())
        await stack.enter_async_context(fhir_mcp.session_manager.run())
        await stack.enter_async_context(matching_mcp.session_manager.run())
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = Starlette(
    routes=[
        # More-specific /mcp/* mounts must come before the legacy /mcp mount.
        Mount(
            "/mcp/discovery",
            discovery_mcp.streamable_http_app(streamable_http_path="/", transport_security=transport_security),
        ),
        Mount(
            "/mcp/analysis",
            analysis_mcp.streamable_http_app(streamable_http_path="/", transport_security=transport_security),
        ),
        Mount(
            "/mcp/fhir",
            fhir_mcp.streamable_http_app(streamable_http_path="/", transport_security=transport_security),
        ),
        Mount(
            "/mcp/matching",
            matching_mcp.streamable_http_app(streamable_http_path="/", transport_security=transport_security),
        ),
        Mount(
            "/mcp",
            mcp.streamable_http_app(streamable_http_path="/", transport_security=transport_security),
        ),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
    )