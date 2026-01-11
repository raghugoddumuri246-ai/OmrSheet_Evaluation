from omr_processor import OMRProcessor
import json
import os
import cv2
import numpy as np

def main():
    template_path = 'template.json'
    pdf_path = 'final_omr.pdf'
    
    if not os.path.exists(template_path):
        print("Error: template.json not found.")
        return

    processor = OMRProcessor(template_path)
    
    # Process PDF
    # Note: For production use, handle errors gracefully or accept image input
    try:
        if os.path.exists(pdf_path):
            images = processor.process_pdf(pdf_path)
            if images:
                image = images[0]
            else:
                raise Exception("No images found in PDF")
        else:
             raise Exception(f"PDF file '{pdf_path}' not found")
    except Exception as e:
        print(f"Warning: {e}")
        print("Using blank image for demonstration of detection logic.")
        dims = processor.page_dims
        image = np.ones((dims[1], dims[0], 3), dtype=np.uint8) * 255

    # 1. Detect Bubbles Dynamically (The "Green" bubbles)
    print("Scanning for bubbles using Computer Vision...")
    raw_bubbles = processor.scan_for_bubbles(image)
    if not raw_bubbles:
        print("Warning: No bubbles detected via CV scan.")
    
    # 2. Map unstructured bubbles to Template Logic (Roll No, Questions)
    print("Mapping detected bubbles to structure...")
    bubbles = processor.map_bubbles_to_structure(raw_bubbles)
    
    # 3. Evaluate (The "Filled/Unfilled" step)
    print("Evaluating filled status...")
    evaluated_bubbles = processor.evaluate_bubbles(image, bubbles)
    
    # 3. Output Results
    # Aggregate results into structured format
    final_output = {
        "rollNumber": "",
        "testBookletCode": "",
        "responses": {},
        "summary": {}
    }
    
    # Process Roll Number
    roll_bubbles = [b for b in evaluated_bubbles if b.get('group') == 'rollNumber' and b.get('filled')]
    roll_bubbles.sort(key=lambda x: x['id']) # Ensure correct digit order if needed
    # Group by column to get digits
    # (Simplified: assuming mapped_bubbles has 'roll_colX_valY')
    
    # Construct Roll Number string
    roll_error_reason = ""
    roll_cols_detected = {}
    for b in roll_bubbles:
        try:
            col_idx = int(b['id'].split('_')[1].replace('col', ''))
            if col_idx not in roll_cols_detected:
                roll_cols_detected[col_idx] = []
            roll_cols_detected[col_idx].append(b['value'])
        except (IndexError, ValueError):
            continue

    if roll_cols_detected:
        final_roll = ""
        final_roll_chars = []
        is_roll_invalid = False
        
        # detailed check
        sorted_cols = sorted(roll_cols_detected.keys())
        if sorted_cols:
             max_col = max(sorted_cols) 
             # We should probably iterate from 1 to max_col (or whatever the start is) to catch missing digits too?
             # For now, let's stick to the user's specific request: "if one digit gerts two bubbles".
             
             for col in sorted_cols:
                 vals = roll_cols_detected[col]
                 if len(vals) > 1:
                     is_roll_invalid = True
                     roll_error_reason = f"Column {col} has {len(vals)} bubbles filled"
                     final_roll_chars.append("?") # Placeholder
                     break # or continue to find more errors? User said "make detected roll number as invalid also add reason"
                 else:
                     final_roll_chars.append(vals[0])
        
        if is_roll_invalid:
            final_output['rollNumber'] = "INVALID"
            final_output['rollValidation'] = roll_error_reason
        else:
            final_output['rollNumber'] = "".join(final_roll_chars)
            final_output['rollValidation'] = "OK"
        
    # --- OCR Validation ---
    print("Performing OCR on Roll Number boxes...")
    ocr_roll = processor.extract_roll_digits(image)
    if ocr_roll == "NO_OCR":
        print("Warning: OCR skipped (pytesseract not found).")
        ocr_roll = ""
    elif ocr_roll:
        print(f"OCR Extracted Roll No: {ocr_roll}")
    
    final_output['ocrRollNumber'] = ocr_roll
    # ----------------------
        
    # Process Responses
    # Group by question number
    q_groups = {}
    for b in evaluated_bubbles:
        if 'q' in b.get('id', '') and b.get('group', '').startswith('col'):
            q_num = str(b.get('question'))
            if q_num not in q_groups: q_groups[q_num] = []
            if b.get('filled'):
                q_groups[q_num].append(b['value'])
                
    for q, selected in q_groups.items():
        if len(selected) == 1:
            final_output['responses'][q] = selected[0]
        elif len(selected) > 1:
            final_output['responses'][q] = "MULTIPLE"
        else:
            final_output['responses'][q] = ""

    # Load Answer Key
    answer_key_path = 'answer_key.json'
    if os.path.exists(answer_key_path):
        with open(answer_key_path, 'r') as f:
            full_key = json.load(f)
            answer_key = full_key.get('answers', {})
    else:
        print("Warning: answer_key.json not found. Using empty key.")
        answer_key = {}
    
    # Scoring
    correct_count = 0
    wrong_count = 0
    unanswered_count = 0
    
    score_details = []
    
    # Determine range of questions to check
    # We check everything in the answer key, or detected, whichever is larger or union
    all_q_nums = set([int(k) for k in final_output['responses'].keys()])
    all_q_nums.update([int(k) for k in answer_key.keys()])
    if not all_q_nums: 
        max_q = 60
    else:
        max_q = max(all_q_nums)
    
    for i in range(1, max_q + 1):
        q_str = str(i)
        response = final_output['responses'].get(q_str, "")
        correct = answer_key.get(q_str, "")
        
        status = "UNANSWERED"
        reason = ""
        if response:
            if response == "MULTIPLE":
                status = "INVALID_MULTIPLE"
                reason = "Multiple options filled"
                wrong_count += 1
            elif response == correct:
                status = "CORRECT"
                correct_count += 1
            else:
                status = "WRONG"
                wrong_count += 1
        else:
            unanswered_count += 1
            
        score_details.append({
            "question": i,
            "marked": response,
            "correct": correct,
            "status": status,
            "reason": reason
        })
        
    final_output['summary'] = {
        "total_questions": max_q,
        "correct": correct_count,
        "wrong": wrong_count,
        "unanswered": unanswered_count,
        "score": correct_count,
        "score": correct_count,
        "score": correct_count,
        "roll_match_ocr": (final_output['rollNumber'] == ocr_roll) if ocr_roll else "N/A"
    }
    final_output['details'] = score_details

    # Save structured JSON
    results_path = 'omr_report.json'
    with open(results_path, 'w') as f:
        json.dump(final_output, f, indent=2)
        
    print(f"\n================ SUMMARY REPORT ================")
    print(f" Detected Bubbles  : {len(evaluated_bubbles)}")
    
    filled_count = sum(1 for b in evaluated_bubbles if b.get('filled'))
    unfilled_count = len(evaluated_bubbles) - filled_count
    
    print(f" Filled Bubbles    : {filled_count}")
    print(f" Unfilled Bubbles  : {unfilled_count}")
    print(f"------------------------------------------------")
    print(f" Detected Roll No  : {final_output['rollNumber'] if final_output['rollNumber'] else 'None'}")
    
    if ocr_roll:
         ocr_status = "MATCH" if (final_output['rollNumber'] == ocr_roll) else "MISMATCH"
         print(f" OCR Extracted     : {ocr_roll}")
         print(f" Roll No Status    : {ocr_status} (OCR Validation)")

    print(f"------------------------------------------------")
    print(f" Correct Answers   : {correct_count}")
    print(f" Wrong Answers     : {wrong_count}")
    print(f" Unanswered        : {unanswered_count}")
    print(f" TOTAL SCORE       : {correct_count} / {max_q}")
    print(f"================================================")
    print(f"Detailed JSON Report saved to {results_path}")
    
    # 4. Save Visual Result
    
    # 4. Save Visual Result
    print("Generating visual report...")
    output_img = processor.draw_bubbles(image, evaluated_bubbles, thickness=3, use_status_color=True)
    
    # Draw OCR ROIs (Cyan boxes) for validation
    output_img = processor.draw_ocr_rois(output_img, color=(255, 255, 0), thickness=2)
    
    cv2.imwrite("omr_evaluated.jpg", output_img)
    print("Visual report saved to omr_evaluated.jpg (Blue=Filled, Green=Unfilled, Yellow=OCR Zones)")

if __name__ == "__main__":
    main()
