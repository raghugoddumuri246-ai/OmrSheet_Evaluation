from omr_processor import OMRProcessor
import json
import os
import cv2
import argparse

def generate_key(pdf_path, output_path='answer_key.json', template_path='template.json'):
    if not os.path.exists(template_path):
        print(f"Error: Template file '{template_path}' not found.")
        return

    if not os.path.exists(pdf_path):
        print(f"Error: Input PDF '{pdf_path}' not found.")
        return

    print(f"Processing Master OMR: {pdf_path}")
    processor = OMRProcessor(template_path)
    
    # Process PDF to get image
    try:
        images = processor.process_pdf(pdf_path)
        if images:
            image = images[0]
        else:
            raise Exception("No images found in PDF")
    except Exception as e:
        print(f"Error processing PDF: {e}")
        return

    # 1. Detect Bubbles
    print("Scanning for bubbles...")
    raw_bubbles = processor.scan_for_bubbles(image)
    if not raw_bubbles:
        print("Error: No bubbles detected.")
        return
    
    # 2. Map to structure
    print("Mapping to structure...")
    bubbles = processor.map_bubbles_to_structure(raw_bubbles)
    
    # 3. Evaluate Filled Status
    print("Evaluating choices...")
    evaluated_bubbles = processor.evaluate_bubbles(image, bubbles)
    
    # 4. Extract Answers
    answers = {}
    
    # Group by question number
    q_groups = {}
    for b in evaluated_bubbles:
        if 'q' in b.get('id', '') and b.get('group', '').startswith('col'):
            q_num = str(b.get('question'))
            if q_num not in q_groups: q_groups[q_num] = []
            if b.get('filled'):
                q_groups[q_num].append(b['value'])
                
    # Finalize Answer Key
    for q, selected in q_groups.items():
        if len(selected) == 1:
            answers[q] = selected[0]
        elif len(selected) > 1:
            print(f"Warning: Question {q} has multiple bubbles filled in Master Key. Using 'MULTIPLE' (or consider invalidating).")
            # For a master key, multiple might be valid if multiple options are allowed, 
            # but usually a key has one answer. Let's store the first one or mark as query.
            # User request didn't specify multi-select keys, so we'll warn.
            answers[q] = selected[0] # Taking first for now, or could store list? standard is single char.
        # If 0, we don't include it in the key (or empty string)

    # Sort checks?
    # Save to JSON
    key_structure = {
        "answers": answers
    }
    
    with open(output_path, 'w') as f:
        json.dump(key_structure, f, indent=2)
        
    print(f"\nSuccess! Generated answer key with {len(answers)} items.")
    print(f"Saved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Answer Key from OMR PDF")
    parser.add_argument("pdf_path", help="Path to the Master OMR PDF file")
    parser.add_argument("--output", default="answer_key.json", help="Output JSON path")
    
    args = parser.parse_args()
    generate_key(args.pdf_path, args.output)
