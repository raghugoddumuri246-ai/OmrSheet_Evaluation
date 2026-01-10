from omr_processor import OMRProcessor
import cv2
import os
import numpy as np

def main():
    template_path = 'template.json'
    pdf_path = 'omr 60.pdf'
    
    if not os.path.exists(pdf_path):
        print(f"Error: {pdf_path} not found.")
        return

    processor = OMRProcessor(template_path)
    
    # 1. Convert PDF
    print("Converting PDF to Image...")
    try:
        images = processor.process_pdf(pdf_path)
        if not images:
            print("No images converted.")
            return
        
        # Take the first page
        image = images[0]
    except Exception as e:
        print(f"Error converting PDF: {e}")
        print("Falling back to blank image for coordinate verification.")
        # Create blank white image
        dims = processor.page_dims
        image = np.ones((dims[1], dims[0], 3), dtype=np.uint8) * 255


    # 2. Resize to verify alignment
    print("Resizing image to template dimensions...")
    resized_img = processor.resize_image(image)
    
    # 3a. Get Template Coordinates (RED)
    print("Calculating expected bubble coordinates from Template...")
    template_bubbles = processor.get_bubble_coordinates()
    print(f"Template defined {len(template_bubbles)} bubbles.")

    # 3b. Scan for Actual Bubbles (GREEN)
    print("Scanning image for bubble shapes (CV Detection)...")
    scanned_bubbles = processor.scan_for_bubbles(resized_img, debug_path='debug_thresh.jpg')
    print(f"Visually detected {len(scanned_bubbles)} candidate bubbles.")

    # 4. detailed Grid Analysis
    print("\n--- Advanced Grid Calibration ---")
    valid_scanned = [b for b in scanned_bubbles if b['area'] > 800]
    
    if len(valid_scanned) < 50:
        print("Not enough bubbles to estimate grid.")
    # 4. Column Cluster Analysis (For Questions)
    print("\n--- Question Column Analysis (Y > 600) ---")
    question_bubbles = [b for b in scanned_bubbles if b['y'] > 600]
    question_bubbles.sort(key=lambda b: b['x'])
    
    if not question_bubbles:
        print("No bubbles found in question area.")
    else:
        # Cluster by X with large gap (e.g. > 150px indicates new column block)
        clusters = []
        current_cluster = []
        last_x = question_bubbles[0]['x']
        
        for b in question_bubbles:
            if b['x'] - last_x > 150: # huge gap -> new column
                clusters.append(current_cluster)
                current_cluster = []
            current_cluster.append(b)
            last_x = b['x']
        clusters.append(current_cluster)
        
        print(f"Found {len(clusters)} Column Blocks.")
        for i, cluster in enumerate(clusters):
            if not cluster: continue
            min_x = min(b['x'] for b in cluster)
            min_y = min(b['y'] for b in cluster)
            max_x = max(b['x'] for b in cluster)
            max_y = max(b['y'] for b in cluster)
            count = len(cluster)
            print(f"  Col {i+1}: Found {count} bubbles. Origin approx: [{min_x}, {min_y}]. Bounds: X[{min_x}-{max_x}], Y[{min_y}-{max_y}]")
            
    print("---------------------------------")
    
    # Analyze Roll Number Block specifically again
    print("\n--- Roll Number Block ---")
    roll_bubbles = [b for b in scanned_bubbles if 300 < b['y'] < 600 and b['x'] < 700]
    if roll_bubbles:
        min_x = min(b['x'] for b in roll_bubbles)
        min_y = min(b['y'] for b in roll_bubbles)
        print(f"Roll Block: {len(roll_bubbles)} bubbles. Origin: [{min_x}, {min_y}]")

        
    print("---------------------------------")

    # 5. Draw
    # Draw Template Bubbles in RED (Expected)
    # debug_img = processor.draw_bubbles(resized_img, template_bubbles, color=(0, 0, 255), thickness=2)
    debug_img = resized_img.copy() # Start fresh with just image
    
    # Draw Valid Scanned Bubbles in GREEN (Actual)
    debug_img = processor.draw_bubbles(debug_img, valid_scanned, color=(0, 255, 0), thickness=2)
    
    # 6. Save
    output_filename = 'debug_bubbles.jpg'
    cv2.imwrite(output_filename, debug_img)
    print(f"Saved visualization to {output_filename}")
    print("GREEN = Detected (Actual). Red bubbles removed as requested.")

if __name__ == "__main__":
    main()
