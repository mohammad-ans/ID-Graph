import yaml
from collections import defaultdict
import hashlib
# FEATURES = ("screen_width", "screen_length", "ip_country", "city", "language", "temporal_same_day", "temporal_same_week", "temporal_same_month", "merchant_name")
# with open("cschema.yaml") as file:
#     data_columns = yaml.safe_load(file)
    
#     names = set(FEATURES)
#     for item in data_columns.get("probabilistic", []) or []:
#         names.update(item.get("fields", {}).keys())
#     print(tuple(sorted(names)))
print(hashlib.sha256("deborah09@hall.net".strip().lower().encode("utf-8")).hexdigest() == hashlib.sha256("deborah09@hall.net".strip().lower().encode("utf-8")).hexdigest())
#     temp = list(data_columns["passthrough"])
#     temp.extend(element["column"] for element in data_columns["identifiers"])
#     # for element in data_columns["signal_groups"]:
#     #     temp.extend(element["columns"])
#     print(data_columns["record_id"][0])
#     print([f"has_{identifier["name"]}" for identifier in data_columns["identifiers"] if identifier["include_in_belongs_to"]])

    # if data_columns["signal_groups"]
# print(f"{'identity':>24}{'ids':>5}{'recs':>6}{'growth':>8}{'diversity':>11}{'burst':>8}{'mean_z':>9}{'max_z':<8}a")
# print(["a"] * 10)