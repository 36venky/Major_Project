"""
api/location.py
────────────────
Patient location management endpoints.

GET    /patients/{patient_id}/location  – retrieve saved location
PUT    /patients/{patient_id}/location  – upsert location (lat, lng, address)
DELETE /patients/{patient_id}/location  – clear location

Location is stored directly on the Patient row (no new table):
  location          TEXT  — "lat,lng"  e.g. "12.9716,77.5946"
  location_address  TEXT  — human-readable address from reverse geocode / user input
  maps_link         TEXT  — https://www.google.com/maps?q=lat,lng

Validation:
  latitude  : -90  … +90
  longitude : -180 … +180
  address   : max 500 chars
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.database.schemas import APIResponse, LocationResponse, LocationUpsert

router = APIRouter(tags=["Location"])


def _maps_link(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat:.7f},{lng:.7f}"


def _parse_location(location_str: str | None) -> tuple[float | None, float | None]:
    """Parse 'lat,lng' string back to floats."""
    if not location_str:
        return None, None
    try:
        parts = location_str.split(",", 1)
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None, None


@router.get(
    "/patients/{patient_id}/location",
    response_model=LocationResponse,
    summary="Get patient location",
)
async def get_location(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> LocationResponse:
    """Return the saved location for a patient, or empty fields if none set."""
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{patient_id}' not found.")

    lat, lng = _parse_location(getattr(patient, "location", None))
    return LocationResponse(
        patient_id=patient_id,
        latitude=lat,
        longitude=lng,
        location_address=getattr(patient, "location_address", None),
        maps_link=getattr(patient, "maps_link", None),
    )


@router.put(
    "/patients/{patient_id}/location",
    response_model=LocationResponse,
    summary="Save / update patient location",
)
async def upsert_location(
    patient_id: str,
    body: LocationUpsert,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> LocationResponse:
    """
    Save or update the patient's location.

    Accepts validated latitude / longitude (and optional address).
    Generates the Google Maps link automatically.
    """
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{patient_id}' not found.")

    lat = round(body.latitude,  7)
    lng = round(body.longitude, 7)
    link = _maps_link(lat, lng)

    await crud.update_patient(db, patient_id, {
        "location":         f"{lat},{lng}",
        "location_address": body.location_address,
        "maps_link":        link,
    })

    return LocationResponse(
        patient_id=patient_id,
        latitude=lat,
        longitude=lng,
        location_address=body.location_address,
        maps_link=link,
    )


@router.delete(
    "/patients/{patient_id}/location",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear patient location",
)
async def delete_location(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> APIResponse:
    """Remove the saved location for a patient."""
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{patient_id}' not found.")

    await crud.update_patient(db, patient_id, {
        "location":         None,
        "location_address": None,
        "maps_link":        None,
    })

    return APIResponse(message=f"Location cleared for patient {patient_id}.")
