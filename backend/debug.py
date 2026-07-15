import sys
sys.path.append('c:\\Users\\SAIKALAMODEPALLI\\Downloads\\SIRA_CAPSTONE\\SIRA\\backend')
from logic.pattern_detector import load_sales, get_effective_today
from datetime import datetime

df = load_sales()
effective_today = get_effective_today(df)
real_today = datetime.now()

print(f"Max InvoiceDate (effective_today): {effective_today}")
print(f"Actual datetime.now(): {real_today}")
print(f"data type of effective_today: {type(effective_today)}")
print(f"Year difference: {real_today.year - effective_today.year}")
