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
signals = ["a", "b"]
# dicto = defaultdict(lambda : {signal : None for signal in signals, "c" : list()})
dicto["a"]["signal"]= "c"
print(dicto["a"])