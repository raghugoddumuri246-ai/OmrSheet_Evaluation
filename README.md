# OMR System Technical Documentation

This document provides an end-to-end explanation of the OMR (Optical Mark Recognition) system's functionality, detailing the specific files and functions responsible for each step of the process.

## Core Files Overview

| File Name | Purpose |
| :--- | :--- |
| **`main.py`** | The entry point of the application. Orchestrates the workflow: loads files, calls the processor, validates data, and generates reports. |
| **`omr_processor.py`** | The "Engine" of the system. Contains the `OMRProcessor` class with all Computer Vision (OpenCV) and OCR logic. |
| **`template.json`** | Configuration file that defines the layout of the OMR sheet (coordinates, bubble sizes, grid structures). |
| **`answer_key.json`** | Contains the correct answers for grading. |

---

## Detailed Workflow

### Phase 1: Initialization & Setup
**Goal:** Prepare the system with the correct sheet layout.

*   **File:** `main.py`
    *   **Function:** `main()`
    *   **Action:** Defines paths for `template.json` and the input PDF (`final_omr.pdf`). Checks if files exist.
*   **File:** `omr_processor.py`
    *   **Class:** `OMRProcessor`
    *   **Function:** `__init__(self, template_path)`
    *   **Action:** Loads the JSON template. Reads `pageDimensions` and `bubbleDimensions` to calibrate expected bubble sizes (radius).

### Phase 2: Image Processing
**Goal:** Convert the input PDF into a format the computer can "read" (High-contrast image).

*   **File:** `omr_processor.py`
    *   **Function:** `process_pdf(pdf_path)`
    *   **Action:** Uses `pdf2image` to convert the PDF pages into high-quality images (300 DPI) for OpenCV processing.
    *   **Function:** `preprocess_image(image)`
    *   **Action:**
        1.  **Grayscale:** Converts color image to black & white.
        2.  **Blur:** Removes noise (grain).
        3.  **Thresholding (`cv2.threshold` + Otsu):** Creates a binary image where ink is pure white and paper is pure black. This is critical for contour detection.

### Phase 3: Bubble Detection
**Goal:** Physically locate every bubble-like shape on the page.

*   **File:** `omr_processor.py`
    *   **Function:** `scan_for_bubbles(image)`
    *   **Logic:**
        1.  **`cv2.findContours`**: Finds all closed shapes.
        2.  **Area Filter**: Checks if the shape's area matches the expected bubble size (defined in `template.json`).
        3.  **Circularity Check**: Uses the formula `4π(Area)/(Perimeter)^2` to ensure the shape is circular (> 0.85).
        4.  **Duplicate Removal**: Checks if multiple circles are found at the same spot (concentric rings) and keeps only the best match.

### Phase 4: Structural Mapping
**Goal:** Give meaning to the detected bubbles (e.g., "This circle is for Question 1, Option A").

*   **File:** `omr_processor.py`
    *   **Function:** `map_bubbles_to_structure(detected_bubbles)`
    *   **Logic:**
        1.  **Y-Split**: Splits the page at `Y=900`.
            *   **Top**: Header Section (Roll Number, Booklet Code).
            *   **Bottom**: Questions Section.
        2.  **Header Mapping**:
            *   Clusters bubbles by X-coordinates to form columns.
            *   Assigns IDs like `roll_col0_val1` based on row position.
        3.  **Question Mapping (Dynamic)**:
            *   Analyzes horizontal gaps between bubbles to automatically detect columns (e.g., 4 columns of 15 questions).
            *   Sorts bubbles into grids and assigns IDs like `q1_A`, `q1_B`.

### Phase 5: Evaluation (Reading Marks)
**Goal:** Decide if a bubble is "Filled" or "Empty".

*   **File:** `omr_processor.py`
    *   **Function:** `evaluate_bubbles(image, bubbles)`
    *   **Logic:**
        1.  **Masking**: Creates a focused mask for the center of each bubble.
        2.  **`cv2.countNonZero`**: Counts white pixels (ink) inside the mask.
        3.  **Threshold**: Calculates a `fill_ratio`. If `fill_ratio > 0.35` (35%), the bubble is marked as `filled: True`.

### Phase 6: Validation (Roll No & OCR)
**Goal:** Verify the student's identity Using Hybrid Validation.

*   **File:** `omr_processor.py`
    *   **Function:** `extract_roll_digits(image)` (OCR)
    *   **Logic:**
        1.  **ROI Detection**: Finds the rectangular strip of boxes for the Roll Number.
        2.  **Grid Partitioning**: Slices the strip into individual digit images.
        3.  **Refinement**: Merges broken digit parts (e.g., a broken '4') into a unified bounding box.
        4.  **`pytesseract`**: Recognizes the digit in each box.
*   **File:** `main.py`
    *   **Logic (Lines ~60-100)**:
        1.  **Bubble Check**: Ensures exactly *one* bubble is filled per column. Checks for "Double Bubbling" errors.
        2.  **Comparison**: Compares `final_output['rollNumber']` (Bubbles) vs `ocr_roll` (Handwritten). Logs a warning if they mismatch.

### Phase 7: Reporting & Summary
**Goal:** Generate the final output for the user.

*   **File:** `main.py`
    *   **Loop (Lines ~160-188)**:
        *   Iterates through every question.
        *   Compares the User Response against `answer_key.json`.
        *   Assigns Status: `CORRECT`, `WRONG`, `UNANSWERED`, or `INVALID_MULTIPLE`.
    *   **Files Generated**:
        1.  **`omr_report.json`**: Complete structured data with scores and detailed question analysis.
        2.  **`omr_evaluated.jpg`**: Visual proof.
            *   **Function:** `draw_bubbles` (Blue=Filled, Green=Empty).
            *   **Function:** `draw_ocr_rois` (Yellow boxes showing what the OCR saw).
