# Test script to design and verify the 5-page 2-parameter OLED display engine
def format_line(s):
    return s[:21].ljust(21)

print("Designing OLED pages:")
for page in range(5):
    print(f"--- PAGE {page+1} ---")
