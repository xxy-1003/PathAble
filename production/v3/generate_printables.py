"""Create vector A4 ArUco markers and a checkerboard at measured sizes."""

from pathlib import Path

import cv2
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


OUTPUT = Path(__file__).resolve().parent / "output" / "pdf" / "PathAble_Markers_and_Checkerboard.pdf"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARKER_MM = 150
CHECKER_SQUARE_MM = 18


def heading(pdf, title, subtitle):
    pdf.setFillColorRGB(0.08, 0.16, 0.27)
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawString(20 * mm, 274 * mm, title)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, 264 * mm, subtitle)
    pdf.setFillColorRGB(0, 0, 0)


def marker_page(pdf, marker_id):
    heading(pdf, f"PathAble junction marker {marker_id}",
            "DICT_4X4_50 | junction wall marker | A4 paper | print at actual size")
    marker = cv2.aruco.generateImageMarker(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), marker_id, 600
    )
    origin_x = (PAGE_WIDTH - MARKER_MM * mm) / 2
    origin_y = 70 * mm
    cell = MARKER_MM * mm / 6
    for row in range(6):
        for column in range(6):
            if marker[row * 100 + 50, column * 100 + 50] < 128:
                pdf.rect(origin_x + column * cell,
                         origin_y + (5 - row) * cell, cell, cell, stroke=0, fill=1)

    pdf.setLineWidth(0.35)
    pdf.line(origin_x, 55 * mm, origin_x + MARKER_MM * mm, 55 * mm)
    for x in (origin_x, origin_x + MARKER_MM * mm):
        pdf.line(x, 52 * mm, x, 58 * mm)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(PAGE_WIDTH / 2, 46 * mm,
                          "Outer black square must measure exactly 150 mm")
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(PAGE_WIDTH / 2, 30 * mm,
                          "Leave the surrounding white space clear; mount flat at chest height.")
    pdf.showPage()


def checkerboard_page(pdf):
    heading(pdf, "PathAble camera calibration checkerboard",
            "9 x 6 inner corners | 18 mm square | A4 paper | print at actual size")
    columns, rows = 10, 7
    cell = CHECKER_SQUARE_MM * mm
    origin_x = (PAGE_WIDTH - columns * cell) / 2
    origin_y = 82 * mm
    for row in range(rows):
        for column in range(columns):
            if (row + column) % 2 == 0:
                pdf.rect(origin_x + column * cell, origin_y + row * cell,
                         cell, cell, stroke=0, fill=1)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(PAGE_WIDTH / 2, 63 * mm,
                          "Check one square with a ruler: exactly 18 mm x 18 mm")
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(PAGE_WIDTH / 2, 45 * mm,
                          "Keep the sheet flat and capture it from varied angles across the frame.")
    pdf.showPage()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("PathAble ArUco junction markers and camera checkerboard")
    pdf.setAuthor("PathAble")
    for marker_id in range(6):
        marker_page(pdf, marker_id)
    checkerboard_page(pdf)
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
