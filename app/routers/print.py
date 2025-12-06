"""Print API endpoints for Universal Print integration."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import Optional
import logging

from app.database import get_db
from app.config import settings
from app.services.auth_service import get_current_user_from_request
from app.services.print_service import get_print_service, ZPLLabelGenerator
from app.models.workstation import LabelPrinter, UserWorkstationPreference
from app.models.document import Document

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/config")
async def get_print_config(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get Universal Print configuration status."""
    get_current_user_from_request(request, db)

    return {
        "enabled": settings.UNIVERSAL_PRINT_ENABLED,
        "configured": bool(
            settings.UNIVERSAL_PRINT_ENABLED and
            settings.AZURE_AD_CLIENT_ID and
            settings.AZURE_AD_CLIENT_SECRET
        ),
        "required_permissions": ["PrintJob.Create", "Printer.Read.All"]
    }


@router.get("/printers")
async def list_printers(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    List available printers.

    Returns both locally configured printers and Universal Print printers (if enabled).
    """
    current_user = get_current_user_from_request(request, db)

    # Get locally configured printers
    local_printers = db.query(LabelPrinter).filter(
        LabelPrinter.is_active == True
    ).all()

    printers = [
        {
            "id": p.id,
            "name": p.name,
            "location": p.location,
            "printer_type": p.printer_type,
            "print_method": p.print_method,
            "universal_print_id": p.universal_print_id,
            "label_size": f"{p.label_width_inches}x{p.label_height_inches}\"",
            "source": "local"
        }
        for p in local_printers
    ]

    # If Universal Print is enabled, fetch from Graph API
    if settings.UNIVERSAL_PRINT_ENABLED:
        try:
            # Get user's access token from session (if available)
            # For now, we rely on locally configured printers with Universal Print IDs
            pass
        except Exception as e:
            logger.warning(f"Could not fetch Universal Print printers: {e}")

    return {
        "printers": printers,
        "universal_print_enabled": settings.UNIVERSAL_PRINT_ENABLED
    }


@router.get("/printers/{printer_id}")
async def get_printer(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get details for a specific printer."""
    get_current_user_from_request(request, db)

    printer = db.query(LabelPrinter).filter(
        LabelPrinter.id == printer_id
    ).first()

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found"
        )

    return {
        "id": printer.id,
        "name": printer.name,
        "location": printer.location,
        "printer_type": printer.printer_type,
        "print_method": printer.print_method,
        "universal_print_id": printer.universal_print_id,
        "label_width_inches": printer.label_width_inches,
        "label_height_inches": printer.label_height_inches,
        "label_width_dpi": printer.label_width_dpi,
        "is_active": printer.is_active
    }


@router.post("/printers")
async def create_printer(
    request: Request,
    db: Session = Depends(get_db)
):
    """Create a new printer configuration."""
    current_user = get_current_user_from_request(request, db)

    data = await request.json()

    printer = LabelPrinter(
        name=data.get("name", "New Printer"),
        location=data.get("location"),
        printer_type=data.get("printer_type", "Zebra"),
        connection_string=data.get("connection_string"),
        universal_print_id=data.get("universal_print_id"),
        print_method=data.get("print_method", "universal_print"),
        label_width_dpi=data.get("label_width_dpi", 203),
        label_width_inches=data.get("label_width_inches", "2"),
        label_height_inches=data.get("label_height_inches", "1"),
        is_active=True
    )

    db.add(printer)
    db.commit()
    db.refresh(printer)

    logger.info(f"Printer created: {printer.name} by {current_user['user_email']}")

    return {
        "success": True,
        "printer_id": printer.id,
        "message": f"Printer '{printer.name}' created"
    }


@router.put("/printers/{printer_id}")
async def update_printer(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update a printer configuration."""
    current_user = get_current_user_from_request(request, db)

    printer = db.query(LabelPrinter).filter(
        LabelPrinter.id == printer_id
    ).first()

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found"
        )

    data = await request.json()

    if "name" in data:
        printer.name = data["name"]
    if "location" in data:
        printer.location = data["location"]
    if "printer_type" in data:
        printer.printer_type = data["printer_type"]
    if "connection_string" in data:
        printer.connection_string = data["connection_string"]
    if "universal_print_id" in data:
        printer.universal_print_id = data["universal_print_id"]
    if "print_method" in data:
        printer.print_method = data["print_method"]
    if "label_width_dpi" in data:
        printer.label_width_dpi = data["label_width_dpi"]
    if "label_width_inches" in data:
        printer.label_width_inches = data["label_width_inches"]
    if "label_height_inches" in data:
        printer.label_height_inches = data["label_height_inches"]
    if "is_active" in data:
        printer.is_active = data["is_active"]

    db.commit()

    logger.info(f"Printer updated: {printer.name} by {current_user['user_email']}")

    return {"success": True, "message": f"Printer '{printer.name}' updated"}


@router.delete("/printers/{printer_id}")
async def delete_printer(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete a printer configuration."""
    current_user = get_current_user_from_request(request, db)

    printer = db.query(LabelPrinter).filter(
        LabelPrinter.id == printer_id
    ).first()

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found"
        )

    name = printer.name
    db.delete(printer)
    db.commit()

    logger.info(f"Printer deleted: {name} by {current_user['user_email']}")

    return {"success": True, "message": f"Printer '{name}' deleted"}


@router.post("/preview-label")
async def preview_label(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Generate ZPL preview for a label.

    Returns the raw ZPL commands that would be sent to the printer.
    """
    get_current_user_from_request(request, db)

    data = await request.json()
    label_type = data.get("label_type", "accession")
    generator = ZPLLabelGenerator()

    if label_type == "accession":
        zpl = generator.accession_label(
            accession_number=data.get("accession_number", "A00000001"),
            patient_name=data.get("patient_name", ""),
            date_of_birth=data.get("date_of_birth", ""),
            collection_date=data.get("collection_date", ""),
            label_width_dots=data.get("label_width_dots", 406),
            label_height_dots=data.get("label_height_dots", 203)
        )
    elif label_type == "specimen":
        zpl = generator.specimen_label(
            accession_number=data.get("accession_number", "A00000001"),
            specimen_type=data.get("specimen_type", "SST"),
            tube_number=data.get("tube_number", 1),
            total_tubes=data.get("total_tubes", 1)
        )
    elif label_type == "barcode":
        zpl = generator.simple_barcode(
            data=data.get("barcode_data", "12345678"),
            label_text=data.get("label_text", "")
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown label type: {label_type}"
        )

    return {
        "zpl": zpl,
        "label_type": label_type
    }


@router.post("/print")
async def print_label(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Print a label to the specified printer.

    For Universal Print, this sends the ZPL via Graph API.
    For direct IP, this would send to the printer's port 9100.
    """
    current_user = get_current_user_from_request(request, db)

    data = await request.json()
    printer_id = data.get("printer_id")
    document_id = data.get("document_id")
    label_type = data.get("label_type", "accession")
    copies = data.get("copies", 1)

    if not printer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="printer_id is required"
        )

    # Get printer config
    printer = db.query(LabelPrinter).filter(
        LabelPrinter.id == printer_id,
        LabelPrinter.is_active == True
    ).first()

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found or inactive"
        )

    # Get document if specified
    document = None
    if document_id:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

    # Generate ZPL
    generator = ZPLLabelGenerator()

    if label_type == "accession" and document:
        zpl = generator.accession_label(
            accession_number=document.accession_number,
            patient_name=data.get("patient_name", ""),
            date_of_birth=data.get("date_of_birth", ""),
            collection_date=data.get("collection_date", ""),
            label_width_dots=printer.label_width_dots,
            label_height_dots=printer.label_height_dots
        )
    else:
        # Use provided data
        zpl = generator.accession_label(
            accession_number=data.get("accession_number", "A00000001"),
            patient_name=data.get("patient_name", ""),
            date_of_birth=data.get("date_of_birth", ""),
            collection_date=data.get("collection_date", ""),
            label_width_dots=printer.label_width_dots,
            label_height_dots=printer.label_height_dots
        )

    # For multiple copies, repeat the ZPL
    if copies > 1:
        zpl = (zpl + "\n") * copies

    # Send to printer based on method
    if printer.print_method == "universal_print":
        if not printer.universal_print_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Printer does not have Universal Print ID configured"
            )

        if not settings.UNIVERSAL_PRINT_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Universal Print is not enabled"
            )

        # TODO: Get user's Graph API access token and send print job
        # For now, return the ZPL that would be sent
        return {
            "success": False,
            "message": "Universal Print integration pending - Graph API token required",
            "zpl_preview": zpl,
            "printer": printer.name,
            "universal_print_id": printer.universal_print_id
        }

    elif printer.print_method == "direct_ip":
        # TODO: Implement direct IP printing (port 9100)
        return {
            "success": False,
            "message": "Direct IP printing not yet implemented",
            "zpl_preview": zpl,
            "printer": printer.name
        }

    else:
        # Local printing - return ZPL for client-side handling
        return {
            "success": True,
            "message": "ZPL generated for local printing",
            "zpl": zpl,
            "printer": printer.name,
            "copies": copies
        }


@router.post("/test/{printer_id}")
async def test_print(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Send a test label to the specified printer.

    Generates a test label with:
    - Printer name
    - Test barcode
    - Timestamp
    - Border to verify alignment
    """
    current_user = get_current_user_from_request(request, db)

    # Get printer config
    printer = db.query(LabelPrinter).filter(
        LabelPrinter.id == printer_id
    ).first()

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found"
        )

    # Generate test label ZPL
    generator = ZPLLabelGenerator()
    zpl = generator.test_label(
        printer_name=printer.name,
        label_width_dots=printer.label_width_dots,
        label_height_dots=printer.label_height_dots
    )

    logger.info(f"Test print requested for printer {printer.name} by {current_user['user_email']}")

    # Send based on print method
    if printer.print_method == "universal_print":
        if not printer.universal_print_id:
            return {
                "success": False,
                "message": "Universal Print ID not configured",
                "zpl": zpl,
                "printer": printer.name
            }

        if not settings.UNIVERSAL_PRINT_ENABLED:
            return {
                "success": False,
                "message": "Universal Print is not enabled. Enable it in settings.",
                "zpl": zpl,
                "printer": printer.name
            }

        # TODO: Send via Graph API when token is available
        return {
            "success": True,
            "message": "Test label generated. Universal Print requires Graph API integration.",
            "zpl": zpl,
            "printer": printer.name,
            "print_method": "universal_print",
            "universal_print_id": printer.universal_print_id,
            "note": "Copy ZPL to Labelary.com to preview, or configure Graph API for actual printing"
        }

    elif printer.print_method == "direct_ip":
        if not printer.connection_string:
            return {
                "success": False,
                "message": "IP address not configured",
                "zpl": zpl,
                "printer": printer.name
            }

        # TODO: Implement direct IP printing to port 9100
        return {
            "success": True,
            "message": "Test label generated for direct IP printing",
            "zpl": zpl,
            "printer": printer.name,
            "print_method": "direct_ip",
            "connection": printer.connection_string,
            "note": "Direct IP printing to port 9100 pending implementation"
        }

    else:
        # Local printing - return ZPL for client-side handling
        return {
            "success": True,
            "message": "Test label generated for local printing",
            "zpl": zpl,
            "printer": printer.name,
            "print_method": "local",
            "note": "Use browser print dialog or copy ZPL to printer utility"
        }


@router.get("/test/{printer_id}/alignment")
async def test_alignment(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Generate an alignment test pattern for the printer.

    Prints corner markers and center crosshairs to verify
    label alignment and print area.
    """
    get_current_user_from_request(request, db)

    printer = db.query(LabelPrinter).filter(
        LabelPrinter.id == printer_id
    ).first()

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found"
        )

    generator = ZPLLabelGenerator()
    zpl = generator.alignment_test(
        label_width_dots=printer.label_width_dots,
        label_height_dots=printer.label_height_dots
    )

    return {
        "success": True,
        "message": "Alignment test pattern generated",
        "zpl": zpl,
        "printer": printer.name,
        "label_size": f"{printer.label_width_inches}x{printer.label_height_inches}\""
    }


@router.get("/user-preference")
async def get_user_printer_preference(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get the current user's printer preference."""
    current_user = get_current_user_from_request(request, db)
    user_id = current_user.get("user_id", current_user["user_email"])

    pref = db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.user_id == user_id
    ).first()

    if pref and pref.label_printer_id:
        printer = db.query(LabelPrinter).filter(
            LabelPrinter.id == pref.label_printer_id
        ).first()

        if printer:
            return {
                "printer_id": printer.id,
                "printer_name": printer.name,
                "printer_location": printer.location
            }

    return {"printer_id": None, "printer_name": None, "printer_location": None}


@router.put("/user-preference")
async def set_user_printer_preference(
    request: Request,
    db: Session = Depends(get_db)
):
    """Set the current user's printer preference."""
    current_user = get_current_user_from_request(request, db)
    user_id = current_user.get("user_id", current_user["user_email"])

    data = await request.json()
    printer_id = data.get("printer_id")

    # Verify printer exists
    if printer_id:
        printer = db.query(LabelPrinter).filter(
            LabelPrinter.id == printer_id
        ).first()
        if not printer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Printer not found"
            )

    # Update or create preference
    pref = db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.user_id == user_id
    ).first()

    if pref:
        pref.label_printer_id = printer_id
    else:
        pref = UserWorkstationPreference(
            user_id=user_id,
            label_printer_id=printer_id
        )
        db.add(pref)

    db.commit()

    return {"success": True, "printer_id": printer_id}
