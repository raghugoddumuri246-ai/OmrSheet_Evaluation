
import cv2
import pytesseract
import os
import glob
import numpy as np

# Set path if needed, though omr_processor sets it usually.
pytesseract.pytesseract.tesseract_cmd = r"C:\tesseract\tesseract.exe"

def debug_ocr():
    debug_dir = "ocr_debug"
    files = glob.glob(os.path.join(debug_dir, "digit_*.png"))
    
    if not files:
        print(f"No digit images found in {debug_dir}")
        return

    # Sort checks? digit_0.png, digit_1.png...
    files.sort(key=lambda x: int(os.path.splitext(os.path.basename(x))[0].split('_')[1]))

    configs = [
        # Standard Single Char
        ('--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789', "Standard PSM 10"),
        # Relaxed Single Char
        ('--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789', "PSM 7 (Line)"),
        # NO Whitelist
        ('--psm 10 --oem 3', "PSM 10 No Whitelist"),
        # Legacy Engine
        ('--psm 10 --oem 0 -c tessedit_char_whitelist=0123456789', "Legacy Engine (OEM 0)"),
    ]
    
    print(f"{'File':<15} | {'Best Guess':<10} | {'Config Used':<30}")
    print("-" * 60)
    
    # Preprocessing Variants
    # 1. Original (Already processed by omr_processor)
    # 2. Erosions/Dilations
    
    for f in files:
        name = os.path.basename(f)
        raw_img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        # Invert (White text on black -> Black text on white)
        # raw_img is from thresholding (0/255). omr_processor provides it as is.
        # Wait, omr_processor saves "best_digit_img" which is 0s and 255s. 
        # Typically tesseract wants black text on white.
        base_img = cv2.bitwise_not(raw_img)
        
        pipelines = [
            ("Scale 2x Cubic", lambda img: cv2.copyMakeBorder(cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)),
            ("Scale 4x Nearest", lambda img: cv2.copyMakeBorder(cv2.resize(img, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_NEAREST), 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)),
            ("Scale 3x Cubic", lambda img: cv2.copyMakeBorder(cv2.resize(img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC), 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)),
            ("No Scale", lambda img: cv2.copyMakeBorder(img, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)),
        ]
        
        found_res = []

        for p_name, p_func in pipelines:
            processed = p_func(base_img)
            
            # Sub-variants: Erosion/Dilation
            kernel = np.ones((2,2),np.uint8)
            v_eroded = cv2.erode(processed, kernel, iterations=1)
            v_dilated = cv2.dilate(processed, kernel, iterations=1)
            
            sub_vars = [("Orig", processed), ("Erod", v_eroded), ("Dil", v_dilated)]
            
            for sv_name, sv_img in sub_vars:
                for cfg, cfg_name in configs:
                    try:
                        txt = pytesseract.image_to_string(sv_img, config=cfg).strip()
                        if txt and txt.isdigit():
                            found_res.append(f"[{p_name}-{sv_name}-{cfg_name}]->{txt}")
                    except:
                        pass
                        
        print(f"--- {name} ---")
        if not found_res:
            print("  No Match")
        else:
            # Print unique results
            unique = set([r.split('->')[1] for r in found_res])
            print(f"  Matches: {unique}")
            # print detail of first few
            for r in found_res[:3]:
                print(f"    {r}")
        
if __name__ == "__main__":
    debug_ocr()
