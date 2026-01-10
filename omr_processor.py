import json
import cv2
import numpy as np
import os
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\tesseract\tesseract.exe"

except ImportError:
    pytesseract = None
from pdf2image import convert_from_path

class OMRProcessor:
    def __init__(self, template_path):
        with open(template_path, 'r') as f:
            self.template = json.load(f)
        
        self.page_dims = tuple(self.template['pageDimensions'])
        self.bubble_dims = tuple(self.template['bubbleDimensions'])
        self.radius = int(min(self.bubble_dims) / 2)

    def process_pdf(self, pdf_path):
        """
        Converts PDF to a list of numpy images (BGR).
        """
        # Force 300 DPI to match standard A4 pixel dimensions (2480x3508)
        pil_images = convert_from_path(pdf_path, dpi=300)
        opencv_images = []
        for pil_img in pil_images:
            open_cv_image = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            opencv_images.append(open_cv_image)
        return opencv_images

    # ... (resize and preprocess can stay the same)

    def scan_for_bubbles(self, image, debug_path=None):
        """
        Dynamically detects bubble-like shapes in the image using Contour detection.
        Includes filtering for size, circularity, and removal of concentric duplicates.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Use simple binary thresholding or adaptive
        # Focusing on dark bubbles on light paper
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                       cv2.THRESH_BINARY_INV, 11, 2)
        
        if debug_path:
            cv2.imwrite(debug_path, thresh)
            print(f"Saved threshold debug image to {debug_path}")
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        # print(f"DEBUG: Found {len(contours)} total contours.")
        
        candidates = []
        
        expected_area = np.pi * (self.radius ** 2)
        # Stricter filter to match visualize_bubbles "valid > 800" logic
        # 44x44 bubble -> radius 22 -> area ~1520.
        # 0.5 * 1520 = 760. This safely removes the 130px noise.
        min_area_filter = expected_area * 0.5
        max_area_filter = expected_area * 5.0
        
        # print(f"DEBUG: Bubble Area Filter [{int(min_area_filter)} - {int(max_area_filter)}] px. (Expected ~{int(expected_area)})")
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if min_area_filter < area < max_area_filter:
                perimeter = cv2.arcLength(cnt, True)
                if perimeter == 0: continue
                circularity = 4 * np.pi * (area / (perimeter * perimeter))
                
                # Check circularity
                # Squares have circ ~0.78. Bubbles ~1.0.
                # Increase to 0.85 to filter out the handwritten boxes in Roll Number.
                if circularity > 0.85:
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"])
                        cY = int(M["m01"] / M["m00"])
                        candidates.append({'x': cX, 'y': cY, 'r': self.radius, 'area': area, 'circ': circularity})

        # Remove Concentric / Overlapping Bubbles (NMS)
        # If two bubbles are very close, keep the one with Area closest to Expected Area? 
        # Or just the larger one? 
        # Debug said 1370 and 1030. Expected 1520. 1370 is closer.
        candidates.sort(key=lambda b: b['area'], reverse=True) # Sort large to small
        
        final_bubbles = []
        for c in candidates:
            # Check collision with already kept bubbles
            is_duplicate = False
            for kept in final_bubbles:
                dist = np.sqrt((c['x'] - kept['x'])**2 + (c['y'] - kept['y'])**2)
                if dist < 10: # If centers are within 10px, it's the same bubble (inner/outer ring)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                final_bubbles.append(c)
                
        # print(f"DEBUG: Kept {len(final_bubbles)} unique bubbles after NMS (removed {len(candidates) - len(final_bubbles)} duplicates).")
        return final_bubbles

    def resize_image(self, image):
        """
        Resizes image to match the template dimensions.
        """
        return cv2.resize(image, self.page_dims)

    def preprocess_image(self, image):
        """
        Resize, Grayscale, Blur, Threshold.
        """
        image = self.resize_image(image)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        # Switch to Otsu's Binarization
        # adaptiveThreshold often fails on solid fills (hollows them out)
        # Otsu finds the global optimal separation between ink and paper
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return image, thresh

    def get_bubble_coordinates(self):
        """
        Parses the template and returns a list of all bubble coordinates.
        Returns: list of dicts { 'x': int, 'y': int, 'id': str, 'group': str, 'value': str }
        """
        bubbles = []
        
        # 1. Process Header Blocks
        header_blocks = self.template.get('headerBlocks', {})
        
        # Roll Number
        if 'rollNumber' in header_blocks:
            rn_conf = header_blocks['rollNumber']
            origin = rn_conf['origin']
            digits = rn_conf['digits']
            rows = rn_conf['rows']
            digits_gap = rn_conf.get('digitsGap', 32)
            labels_gap = rn_conf.get('labelsGap', 26)
            labels = rn_conf.get('labels', [str(i) for i in range(rows)])
            
            for d in range(digits):
                for r in range(rows):
                    x = origin[0] + (d * digits_gap)
                    y = origin[1] + (r * labels_gap)
                    bubbles.append({
                        'x': int(x),
                        'y': int(y),
                        'r': self.radius,
                        'group': 'rollNumber',
                        'id': f'roll_col{d}_val{labels[r]}',
                        'value': labels[r]
                    })

        # Test Booklet Code
        if 'testBookletCode' in header_blocks:
            tb_conf = header_blocks['testBookletCode']
            origin = tb_conf['origin']
            options = tb_conf['options']
            bubbles_gap = tb_conf.get('bubblesGap', 26)
            
            for i, opt in enumerate(options):
                x = origin[0] + (i * bubbles_gap)
                y = origin[1]
                bubbles.append({
                    'x': int(x),
                    'y': int(y),
                    'r': self.radius,
                    'group': 'testBookletCode',
                    'id': f'testBooklet_{opt}',
                    'value': opt
                })

        # 2. Process Field Blocks (Questions)
        field_blocks = self.template.get('fieldBlocks', {})
        defaults = self.template.get('fieldDefaults', {})
        
        def_bubbles_gap = defaults.get('bubblesGap', 26)
        def_labels_gap = defaults.get('labelsGap', 32)
        def_rows_per_block = defaults.get('rowsPerBlock', 12)
        def_options_count = defaults.get('optionsCount', 4)
        
        options_list = ["A", "B", "C", "D", "E"] # Generic

        for block_name, block_conf in field_blocks.items():
            origin = block_conf['origin']
            # Parse question range "q1..12" -> start=1
            q_range = block_conf.get('questionRange', 'q1..1')
            q_start_str = q_range.replace('q', '').split('..')[0]
            try:
                q_start = int(q_start_str)
            except:
                q_start = 1
                
            rows = block_conf.get('rows', def_rows_per_block)
            bubbles_gap = block_conf.get('bubblesGap', def_bubbles_gap) # Horizontal
            labels_gap = block_conf.get('labelsGap', def_labels_gap)    # Vertical
            options_count = block_conf.get('optionsCount', def_options_count)
            
            for r in range(rows):
                # Calculate Y first (row)
                y = origin[1] + (r * labels_gap)
                q_num = q_start + r
                
                for c in range(options_count):
                    # Calculate X (column/option)
                    x = origin[0] + (c * bubbles_gap)
                    opt_val = options_list[c] if c < len(options_list) else str(c)
                    
                    bubbles.append({
                        'x': int(x),
                        'y': int(y),
                        'r': self.radius,
                        'group': block_name,
                        'id': f'q{q_num}_{opt_val}',
                        'value': opt_val,
                        'question': q_num
                    })
                    
        return bubbles

    def map_bubbles_to_structure(self, detected_bubbles):
        """
        Maps detected bubbles to structure using Strict Spatial Zoning.
        1. Vertical Split: Hardcoded at Y=600 (Based on visual calibration).
           - Top (<600): Roll Number (Left), Booklet (Right).
           - Bottom (>=600): Question Columns.
        2. Horizontal Split (Questions): Auto-cluster into 5 groups using top 4 gaps.
        """
        mapped_bubbles = []
        
        # Strict Y-Split
        # Increased to 900 to ensure full Roll Number block (which ends around Y=880) is captured.
        # This prevents Roll Number tail from being confused with Question Column 1.
        HEADER_Y_LIMIT = 900
        
        # Split pool
        header_pool = [b for b in detected_bubbles if b['y'] < HEADER_Y_LIMIT]
        question_pool = [b for b in detected_bubbles if b['y'] >= HEADER_Y_LIMIT]
        
        # print(f"DEBUG: Strict Y-Split at {HEADER_Y_LIMIT}. Header Bubbles: {len(header_pool)}, Question Bubbles: {len(question_pool)}")
        
        # --- 1. Map Roll Number (Top-Left) ---
        header_blocks = self.template.get('headerBlocks', {})
        if 'rollNumber' in header_blocks:
            conf = header_blocks['rollNumber']
            rows = conf.get('rows', 10)
            digits = conf.get('digits', 9) 
            labels = conf.get('labels', [str(i) for i in range(rows)])
            
            # Filter: X < 1100 from Header Pool
            roll_candidates = [b for b in header_pool if b['x'] < 1100]
            roll_candidates.sort(key=lambda b: b['x'])
            
            # Cluster columns (Gap > 30)
            cols = []
            if roll_candidates:
                curr_col = [roll_candidates[0]]
                for i in range(1, len(roll_candidates)):
                    b = roll_candidates[i]
                    if b['x'] - roll_candidates[i-1]['x'] > 30: 
                         cols.append(curr_col)
                         curr_col = []
                    curr_col.append(b)
                cols.append(curr_col)
            
            # print(f"DEBUG: Found {len(cols)} columns in Roll Number zone.")
            
            for d_idx, col_bubbles in enumerate(cols):
                if d_idx >= digits: break
                col_bubbles.sort(key=lambda b: b['y'])
                for r_idx, b in enumerate(col_bubbles):
                    if r_idx < rows:
                        lbl = labels[r_idx] if r_idx < len(labels) else str(r_idx)
                        b['id'] = f'roll_col{d_idx}_val{lbl}'
                        b['group'] = 'rollNumber'
                        b['value'] = lbl
                        mapped_bubbles.append(b)

        # --- 2. Map Booklet (Top-Right) ---
        if 'testBookletCode' in header_blocks:
             conf = header_blocks['testBookletCode']
             options = conf.get('options', [])
             
             # Filter: X > 1100 from Header Pool
             booklet_candidates = [b for b in header_pool if b['x'] > 1100]
             booklet_candidates.sort(key=lambda b: b['x'])
             
             for i, b in enumerate(booklet_candidates):
                 if i < len(options):
                     opt = options[i]
                     b['id'] = f'testBooklet_{opt}'
                     b['group'] = 'testBookletCode'
                     b['value'] = opt
                     mapped_bubbles.append(b)

        # --- 3. Process Questions (Bottom Area) ---
        q_pool = question_pool[:]
        q_pool.sort(key=lambda b: b['x'])
        
        # We need to find the column structure dynamically to support 60/90/120 questions.
        # Instead of hardcoding 5 columns, we detect significant X-gaps.
        if len(q_pool) < 20:
             print("Warning: Too few bubbles for questions.")
             return mapped_bubbles
             
        gaps = []
        for i in range(1, len(q_pool)):
            gaps.append((q_pool[i]['x'] - q_pool[i-1]['x'], i))
            
        # Filter for "Column Separator" gaps (typically > 80px)
        # Bubble gap is ~40px. Column gap is > 100px.
        # LOWERED to 60 for 90-question sheet which might be tighter.
        
        # Debug Gaps
        all_large_gaps = [g[0] for g in gaps if g[0] > 30]
        print(f"DEBUG: All X-gaps > 30px: {all_large_gaps}")
        
        column_gaps = [g for g in gaps if g[0] > 60]
        
        # Sort by index to get left-to-right splits
        split_indices = sorted([g[1] for g in column_gaps])
        
        num_detected_cols = len(split_indices) + 1
        # print(f"DEBUG: Detected {num_detected_cols} Question Columns (Gaps: {[int(g[0]) for g in column_gaps]})")
        
        question_cols = []
        start_idx = 0
        for split_idx in split_indices:
            question_cols.append(q_pool[start_idx:split_idx])
            start_idx = split_idx
        question_cols.append(q_pool[start_idx:])

        # Map to Template Field Blocks dynamically
        # We assume the columns map to "Block 1", "Block 2"...
        field_blocks = self.template.get('fieldBlocks', {})
        sorted_template_blocks = sorted(field_blocks.items(), key=lambda item: item[1]['origin'][0])
        
        field_defaults = self.template.get('fieldDefaults', {})
        def_rows = field_defaults.get('rowsPerBlock', 12)
        def_opts = field_defaults.get('optionsCount', 4)
        options_list = ["A", "B", "C", "D", "E"]
        
        for i, (name, conf) in enumerate(sorted_template_blocks):
            if i >= len(question_cols):
                # If we detected fewer columns than blocks, stop or continue
                # print(f"Warning: No detected column found for block '{name}'")
                continue
                
            col_cluster = question_cols[i]
            col_cluster.sort(key=lambda b: b['y'])
            
            rows = conf.get('rows', def_rows)
            opts = conf.get('optionsCount', def_opts)
            
            # Dynamic Row Clustering
            grid_rows = []
            if col_cluster:
                curr_row = [col_cluster[0]]
                for b_idx in range(1, len(col_cluster)):
                    b = col_cluster[b_idx]
                    if b['y'] - col_cluster[b_idx-1]['y'] > 25: 
                        grid_rows.append(curr_row)
                        curr_row = []
                    curr_row.append(b)
                grid_rows.append(curr_row)
            
            # Use dynamic column count for numbering
            total_cols_in_layout = num_detected_cols
            
            for r_idx, row_bubbles in enumerate(grid_rows):
                row_bubbles.sort(key=lambda b: b['x'])
                
                # q_num calculation dynamic
                # formula: (RowIndex * TotalCols) + (ColIndex + 1)
                q_num = (r_idx * total_cols_in_layout) + (i + 1)
                
                for c_idx, bubble in enumerate(row_bubbles):
                    if c_idx < opts:
                        opt_val = options_list[c_idx] if c_idx < len(options_list) else str(c_idx)
                        bubble['id'] = f'q{q_num}_{opt_val}'
                        bubble['group'] = name
                        bubble['value'] = opt_val
                        bubble['question'] = q_num
                        mapped_bubbles.append(bubble)
                        
        return mapped_bubbles






    def draw_bubbles(self, image, bubbles, color=(0, 255, 0), thickness=2, use_status_color=False):
        """
        Draws list of bubbles on the image.
        If use_status_color is True:
          - Filled: Blue (255, 0, 0) 
          - Unfilled: Green (0, 255, 0)
        """
        annotated_img = image.copy()
        for b in bubbles:
            draw_color = color
            if use_status_color and 'filled' in b:
                if b['filled']:
                    draw_color = (255, 0, 0) # Blue in BGR
                else:
                    draw_color = (0, 255, 0) # Green in BGR
            
            cv2.circle(annotated_img, (b['x'], b['y']), b['r'], draw_color, thickness)
            
            # Draw ID for debugging if filled
            # if 'filled' in b and b['filled']:
            #     cv2.putText(annotated_img, b['id'], (b['x'], b['y']), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

        return annotated_img

    def evaluate_bubbles(self, image, bubbles):
        """
        Checks each bubble to see if it is filled.
        Returns the list of bubbles with an added 'filled' (bool) key.
        """
        # Preprocess to get binary threshold image
        _, thresh_img = self.preprocess_image(image)
        
        # Get threshold configs
        b_style = self.template.get('bubbleStyle', {})
        fill_threshold = b_style.get('fillThreshold', 0.5) # Increased default slightly
        
        print("\n--- Evaluating Bubbles ---")
        print(f"Fill Threshold: {fill_threshold}")
        
        filled_count = 0
        
        # Calculate ratios for all bubbles first
        for b in bubbles:
            # Create mask for the bubble - checking INNER region only to avoid borders
            mask_radius = int(b['r'] * 0.6)
            if mask_radius < 2: mask_radius = 2
            
            mask = np.zeros(thresh_img.shape, dtype=np.uint8)
            cv2.circle(mask, (b['x'], b['y']), mask_radius, 255, -1)
            
            # Bitwise AND to get pixels inside the bubble
            bubble_pixels = cv2.bitwise_and(thresh_img, thresh_img, mask=mask)
            
            # Count non-zero pixels (white ink on black background)
            total_pixels = np.pi * (mask_radius ** 2)
            filled_pixels = cv2.countNonZero(bubble_pixels)
            
            ratio = filled_pixels / total_pixels if total_pixels > 0 else 0
            b['fill_ratio'] = ratio
            
        # Analysis for Calibration
        sorted_bubbles = sorted(bubbles, key=lambda b: b['fill_ratio'], reverse=True)
        # print("DEBUG: Top 10 Highest Fill Ratios detected:")
        # for i in range(min(10, len(sorted_bubbles))):
        #     sb = sorted_bubbles[i]
        #     print(f"  {sb.get('id')} : {sb['fill_ratio']:.3f}")
            
        fill_threshold = 0.35
        
        # Checking if template has a value, else use 0.35
        t_thresh = b_style.get('fillThreshold', 0.35)
        print(f"Using Threshold: {t_thresh}")
        
        # Debug specific user claimed bubbles
        # target_qs = [2, 7, 37]
        # print(f"DEBUG: Checking specific user-claimed bubbles (Questions {target_qs}):")
        # for b in bubbles:
        #     if b.get('question') in target_qs:
        #          print(f"  ID: {b['id']} | Ratio: {b['fill_ratio']:.3f} | Filled: {b['fill_ratio'] >= t_thresh}")
        
        filled_count = 0
        for b in bubbles:
            is_filled = b['fill_ratio'] >= t_thresh
            b['filled'] = is_filled
            if is_filled:
                filled_count += 1
                
        print(f"Total Bubbles Evaluated: {len(bubbles)}. Filled: {filled_count}")
        return bubbles

    def _get_roll_roi_boxes(self, image):
        """
        Helper: Detects the admission number strip and calculates the N boxes
        by dividing the strip width equally.
        Returns: list of (x, y, w, h) for each digit column (global coords).
        """
        boxes = []
        header_blocks = self.template.get('headerBlocks', {})
        rn_conf = header_blocks.get('rollNumber')
        if not rn_conf: return []
            
        origin = rn_conf['origin']
        digits_count = rn_conf['digits']
        digits_gap = rn_conf.get('digitsGap', 48)
        
        # 1. Broad Search Region (Top of page)
        # Center X from Config
        s_cx = origin[0] + (digits_count * digits_gap) // 2
        s_w = (digits_count * digits_gap) + 150 # Narrower search to avoid outer container
        search_x1 = max(0, int(s_cx - s_w/2))
        search_x2 = int(s_cx + s_w/2)
        
        # Y from Config (Above origin bubbles, limiting to safe area)
        # Bubbles start around Y=320. Search Y=100 to Y=300.
        search_y1 = max(0, origin[1] - 200)
        search_y2 = origin[1] - 30
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        search_roi = gray[int(search_y1):int(search_y2), int(search_x1):int(search_x2)]
        
        # 2. Find the Strip
        _, thresh = cv2.threshold(search_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Horizontal Morph to connect lines/text
        # Reduced kernel width to prevent merging 'Admission No' text with the box
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_strip = None
        max_area = 0
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # Filter: Must be wide (> 6 digits approx 200px) and not too tall
            if w < 200: continue
            if h < 20: continue
            
            area = w * h
            if area > max_area:
                max_area = area
                best_strip = (x, y, w, h)
                
        # 3. Calculate Grid
        if best_strip:
            sx, sy, sw, sh = best_strip
            strip_x = search_x1 + sx
            strip_y = search_y1 + sy
            strip_w = sw
            strip_h = sh
            
            # --- VERTICAL GRID LINE DETECTION ---
            # Isolate the strip ROI
            strip_roi = search_roi[sy:sy+sh, sx:sx+sw]
            
            # Binary Threshold
            _, s_thresh = cv2.threshold(strip_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # Morph Open with Vertical Kernel to keep ONLY vertical lines
            # Grid lines are usually thin and tall. 
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 20))
            v_morph = cv2.morphologyEx(s_thresh, cv2.MORPH_OPEN, v_kernel)
            
            # Find contours of lines
            v_cnts, _ = cv2.findContours(v_morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            line_xs = []
            for c in v_cnts:
                bx, by, bw, bh = cv2.boundingRect(c)
                # Filter: Must be tall (at least 50% of strip height)
                if bh > sh * 0.5:
                    line_xs.append(bx)
            
            line_xs.sort()
            
            # Group nearby lines (thick borders might produce double lines)
            # We want the center of each line.
            final_lines = []
            if line_xs:
                curr_group = [line_xs[0]]
                for x in line_xs[1:]:
                    if x - curr_group[-1] < 10: # If lines are within 10px, same separator
                        curr_group.append(x)
                    else:
                        # Avg of group
                        final_lines.append(sum(curr_group)//len(curr_group))
                        curr_group = [x]
                final_lines.append(sum(curr_group)//len(curr_group))
            
            print(f"DEBUG: Found {len(final_lines)} Vertical Lines: {final_lines}")
            
            # We expect ~10 lines for 9 boxes (or more if double borders). 
            # If we generally see 9+ lines, we can try to form boxes.
            
            # Heuristic: Calculate flow from lines
            valid_intervals = []
            for i in range(len(final_lines) - 1):
                x1 = final_lines[i]
                x2 = final_lines[i+1]
                width = x2 - x1
                if 40 < width < 80: # Expecting ~50-60px
                    valid_intervals.append(width)
            
            # If we found consistent intervals, use their median as cell_w
            calculated_cell_w = None
            if len(valid_intervals) >= 4: # at least 4 consistent gaps
                valid_intervals.sort()
                median_w = valid_intervals[len(valid_intervals)//2]
                print(f"DEBUG: Calculated Median Cell Width: {median_w}")
                calculated_cell_w = median_w
            
            if calculated_cell_w:
                print("DEBUG: Using Dynamic Cell Width + Center Alignment.")
                cell_w = calculated_cell_w
                grid_total_w = digits_count * cell_w
                
                # Center the grid in the strip
                # Offset: (StripW - GridW) / 2
                x_offset = (strip_w - grid_total_w) // 2
                start_x = strip_x + x_offset
                
                boxes = []
                for i in range(digits_count):
                    bx = int(start_x + (i * cell_w))
                    by = int(strip_y)
                    bw = int(cell_w)
                    bh = int(strip_h)
                    boxes.append((bx, by, bw, bh))
                return boxes

            # --- FALLBACK (If lines detection fails) ---
            print("DEBUG: Line detection insufficient. Using robust fallback.")
            
            # Use the verified offset from manual testing
            # Start X = Origin - 68
            start_x = origin[0] - 68
            cell_w = digits_gap # Default 48 if dynamic failed (likely mismatch)

            for i in range(digits_count):
                bx = int(start_x + (i * cell_w))
                by = int(strip_y)
                bw = int(cell_w)
                bh = int(strip_h)
                boxes.append((bx, by, bw, bh))
                
        else:
            # Fallback: No Strip Found
            # print("DEBUG: Dynamic Strip NOT Found. Using Fallback Template Grid.")
            box_bottom = origin[1] - 35
            box_top = box_bottom - 60
            
            # Fallback X
            start_x = origin[0] - 68
            
            for d in range(digits_count):
                x1 = int(start_x + (d * digits_gap))
                y1 = int(box_top)
                w = digits_gap
                h = 60 # approx
                boxes.append((x1, y1, w, h))
                
        return boxes


    def draw_ocr_rois(self, image, color=(255, 0, 255), thickness=2): 
        """
        Draws the Hybrid OCR boxes:
        - Magenta: Calculated Grid Box (from Strip Partition)
        - Green: Inner Digit Blob (if found)
        """
        annotated_img = image.copy()
        
        # Get Boxes
        boxes = self._get_roll_roi_boxes(image)
        if not boxes: return annotated_img
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        for (bx, by, bw, bh) in boxes:
            # Draw Grid Box (Magenta)
            cv2.rectangle(annotated_img, (bx, by), (bx+bw, by+bh), color, thickness)
            
            # Draw Inner Digit (Green) - Simulating Extraction Logic
            # Inner crop to avoid borders
            pad_x = 4
            roi = gray[by:by+bh, bx+pad_x:bx+bw-pad_x]
            if roi.size == 0: continue
            
            _, c_thresh = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            c_cnts, _ = cv2.findContours(c_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            cell_h, cell_w = roi.shape
            valid_candidates = []
            for c in c_cnts:
                cx, cy, cw, ch = cv2.boundingRect(c)
                # Same filters as extraction
                if cw < 2 or ch < 10: continue
                if ch > (cell_h * 0.95): continue 
                valid_candidates.append((cx, cy, cw, ch))
                
            if valid_candidates:
                # Pick largest
                best_c = max(valid_candidates, key=lambda b: b[2] * b[3])
                cx, cy, cw, ch = best_c
                # Map to global
                g_cx = bx + pad_x + cx
                g_cy = by + cy
                cv2.rectangle(annotated_img, (g_cx, g_cy), (g_cx+cw, g_cy+ch), (0, 255, 0), 1)

        return annotated_img

    def extract_roll_digits(self, image):
        """
        Extracts digits using Dynamic Strip Partitioning.
        """
        if pytesseract is None:
            return "NO_OCR"

        boxes = self._get_roll_roi_boxes(image)
        if not boxes: return None
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Debug Image
        # We'll zoom into the relevant strip area for the debug image
        # Find bounds of all boxes
        min_x = min([b[0] for b in boxes])
        max_x = max([b[0]+b[2] for b in boxes])
        min_y = min([b[1] for b in boxes])
        max_y = max([b[1]+b[3] for b in boxes])
        
        pad = 20
        d_x1, d_y1 = max(0, min_x - pad), max(0, min_y - pad)
        d_x2, d_y2 = min(gray.shape[1], max_x + pad), min(gray.shape[0], max_y + pad)
        
        debug_strip = image[d_y1:d_y2, d_x1:d_x2].copy()
        
        detected_res = []
        debug_dir = "ocr_debug"
        if not os.path.exists(debug_dir): os.makedirs(debug_dir)

        for idx, (bx, by, bw, bh) in enumerate(boxes):
            # Crop Cell with Inner Padding to remove Grid Borders
            pad_x = 4
            cell_roi = gray[by:by+bh, bx+pad_x:bx+bw-pad_x]
            
            # --- DEBUG DRAWING on STRIP ---
            # Draw Grid (Blue) on debug_strip
            # Map global bx to local debug_strip
            local_x = bx - d_x1
            local_y = by - d_y1
            cv2.rectangle(debug_strip, (local_x, local_y), (local_x+bw, local_y+bh), (255, 0, 0), 1)
            
            if cell_roi.size == 0:
                detected_res.append("?")
                continue
                
            # 1. Pre-process
            _, c_thresh = cv2.threshold(cell_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # 2. Find Digit Blob
            c_cnts, _ = cv2.findContours(c_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            best_digit_img = None
            cell_h, cell_w = cell_roi.shape
            
            valid_candidates = []
            for c in c_cnts:
                cx, cy, cw, ch = cv2.boundingRect(c)
                if cw < 2 or ch < 10: continue
                if ch > (cell_h * 0.95): continue # vertical line border
                valid_candidates.append((cx, cy, cw, ch))
            
            if valid_candidates:
                # UNIFIED BOUNDING BOX STRATEGY
                # Instead of picking the largest, we merge all valid candidates
                # This handles broken digits (like '4' split into parts)
                
                # Find min/max bounds
                u_x1 = min([b[0] for b in valid_candidates])
                u_y1 = min([b[1] for b in valid_candidates])
                u_x2 = max([b[0]+b[2] for b in valid_candidates])
                u_y2 = max([b[1]+b[3] for b in valid_candidates])
                
                uw = u_x2 - u_x1
                uh = u_y2 - u_y1
                
                # Digit Crop (Union)
                digit_crop = c_thresh[u_y1:u_y2, u_x1:u_x2]
                
                # Square Canvas
                dim = max(uw, uh) + 10
                square_img = np.zeros((dim, dim), dtype=np.uint8)
                off_x = (dim - uw) // 2
                off_y = (dim - uh) // 2
                square_img[off_y:off_y+uh, off_x:off_x+uw] = digit_crop
                best_digit_img = square_img
                
                # Draw Digit Box (Green) on debug_strip
                dg_mx = local_x + pad_x + u_x1
                dg_my = local_y + u_y1
                cv2.rectangle(debug_strip, (dg_mx, dg_my), (dg_mx+uw, dg_my+uh), (0, 255, 0), 1)

            if best_digit_img is None:
                best_digit_img = c_thresh
            
            # OCR Strategy: Multi-Pass
            # Some digits (1, 4, 6) need thickening (erosion).
            # Some digits (9) need to stay thin (original) to avoid closing loops.
            
            # Prepare Variants
            base_img = cv2.bitwise_not(best_digit_img)
            base_img = cv2.resize(base_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            base_img = cv2.copyMakeBorder(base_img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            
            kernel = np.ones((2,2),np.uint8)
            img_eroded = cv2.erode(base_img, kernel, iterations=1) # Thicken
            img_dilated = cv2.dilate(base_img, kernel, iterations=1) # Thin
            
            # Try ERODED first (Best for 4, 6, 1)
            # Try ORIGINAL second (Best for 9)
            # Try DILATED last (If stroke is too thick)
            
            found_digit = "?"
            for name, img_variant in [("eroded", img_eroded), ("original", base_img), ("dilated", img_dilated)]:
                try:
                    txt = pytesseract.image_to_string(img_variant, config='--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789')
                    c = txt.strip()
                    if c and c.isdigit():
                        found_digit = c[0]
                        break
                except:
                    continue
            
            if found_digit == "?":
                # Fallback: Raw OCR + Typo Correction
                # Tesseract often misclassifies handwritten digits as letters/symbols
                try:
                    raw_txt = pytesseract.image_to_string(base_img, config='--psm 10 --oem 3').strip()
                    
                    corrections = {
                        '|': '1', 'I': '1', 'l': '1', '!': '1', ']': '1',
                        'A': '4', 'H': '4', 
                        'b': '6', 'G': '6',
                        'g': '9', 'q': '9',
                        'S': '5', 's': '5', '$': '5',
                        'Z': '2', 'z': '2',
                        'B': '8',
                        'O': '0', 'D': '0'
                    }
                    
                    # Direct match
                    if raw_txt in corrections:
                        found_digit = corrections[raw_txt]
                    
                    # Fuzzy match (e.g. "A." -> "4")
                    elif len(raw_txt) > 0:
                        clean_char = raw_txt[0] 
                        if clean_char in corrections:
                            found_digit = corrections[clean_char]
                        # Handle specific multi-char artifacts
                        if "A" in raw_txt: found_digit = '4'
                except:
                    pass
            
            detected_res.append(found_digit)
        cv2.imwrite(f"{debug_dir}/2_final_boxes.png", debug_strip)
        
        return "".join(detected_res)
