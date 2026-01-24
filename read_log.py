
try:
    with open('debug_dist.txt', 'r', encoding='utf-16-le') as f:
        for line in f:
            if "Dist:" in line:
                print(line.strip())
except Exception as e:
    print(e)
