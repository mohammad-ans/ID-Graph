import yaml
from collections import defaultdict

# with open("schema.yaml") as file:
#     data_columns = yaml.safe_load(file)
#     temp = list(data_columns["passthrough"])
#     temp.extend(element["column"] for element in data_columns["identifiers"])
#     # for element in data_columns["signal_groups"]:
#     #     temp.extend(element["columns"])
#     print(data_columns["record_id"][0])
#     print([f"has_{identifier["name"]}" for identifier in data_columns["identifiers"] if identifier["include_in_belongs_to"]])

    # if data_columns["signal_groups"]
print([c for c, _ in [("screen_width", None), ("screen_length", None), ("ip_country", None), ("city", None), ("language", None)]] + ['screen_width', 'screen_length', 'ip_country', 'city', 'language'])