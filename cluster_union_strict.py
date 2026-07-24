from nebula_client import NebulaClient
from collections import defaultdict
import datetime

class UnionFind:
    """Root Union Find"""
    pair_cluster : dict[tuple, int]
    cluster_pair : dict[int, set]
    cluster_count : int
    def __init__(self):
        self.pair_cluster = {}
        self.cluster_pair = {}
        self.cluster_count = 1

    def ensure_root(self, pairs : list):
        self.cluster_pair[self.cluster_count] = set(pairs)
        for pair in pairs:
            self.pair_cluster[pair] = self.cluster_count
        self.cluster_count += 1

    def union(self, pairs : list[tuple[str]]):
        clusters : set[int] = set()
        for pair in pairs:
            if pair in self.pair_cluster:
                clusters.add(self.pair_cluster[pair])

        if len(clusters) == 0:
            self.ensure_root(pairs)
        elif len(clusters) == 1:
            cluster_no = clusters.pop()
            for pair in pairs:
                self.cluster_pair[cluster_no].add(pair)
                self.pair_cluster[pair] = cluster_no
        else:
            max_cluster = max(clusters, key=lambda c : len(self.cluster_pair[c]))
            clusters.discard(max_cluster)
            for cluster in clusters:
                for pair in self.cluster_pair[cluster]:
                    self.pair_cluster[pair] = max_cluster
                    self.cluster_pair[max_cluster].add(pair)
                self.cluster_pair[cluster].clear()

            for pair in pairs:
                self.cluster_pair[max_cluster].add(pair)
                self.pair_cluster[pair] = max_cluster 


def fetch_identifiers(identity_vid : str, nebula : NebulaClient, signals : list[str], identifiers : list[str]):
    identifier_identity_edges = ",".join([f"has_{identifier}" for identifier in identifiers])
    signals_query_part = ",".join([f"properties($$).{signal} AS {signal} " for signal in signals])

    result = nebula.execute(
    f'GO FROM "{identity_vid}" OVER belongs_to REVERSELY '
    f'WHERE properties(edge).end_date == "" '
    f'YIELD src(edge) AS identifier_vid '
    f'| GO FROM $-.identifier_vid OVER {identifier_identity_edges} REVERSELY '
    f'YIELD src(edge) AS record_vid, '
    f'$-.identifier_vid AS identifier_vid, '
    f'{signals_query_part}'
    )
    by_record = defaultdict(lambda: {signal : None for signal in signals})

    for i in range(result.row_size()):
        row = [v.cast() for v in result.row_values(i)]
        r = by_record[row[0]]
        r.setdefault("identifiers", []).append(row[1])
        i = 2
        for signal in signals:
            r[signal] = row[i]
            i += 1

    return by_record

def cluster_identifiers_strict(identity_vid : str, nebula : NebulaClient, schema_cols : dict):
    uf = UnionFind()
    signals = [signal["name"] for signal in schema_cols["signal_groups"]]
    identifiers = [identifier["name"] for identifier in schema_cols["identifiers"] if identifier["include_in_belongs_to"]]

    record_identifiers = fetch_identifiers(identity_vid, nebula, signals, identifiers)
    identifier_count : dict[str, int] = {}
    for record_data in record_identifiers.values():
        for identifier in record_data["identifiers"]:
            identifier_count[identifier] = identifier_count.get(identifier, 0) + 1
        pairs = generate_pairs(record_data["identifiers"], [record_data[signal] for signal in signals])
        uf.union(pairs)
    if len(uf.cluster_pair) == 1:
        return None
    
    cluster_identifier : dict[int, set]= defaultdict(set)
    identifier_clusters : dict[str, dict] = defaultdict(dict)
    for cluster in uf.cluster_pair:
        for pair in uf.cluster_pair[cluster]:
            cluster_identifier[cluster].add(pair[0])
            identifier_clusters[pair[0]][cluster] = identifier_clusters[pair[0]].get(cluster, 0) + 1
            if is_identifier_check(identifiers, pair[1]):
                cluster_identifier[cluster].add(pair[1])
                identifier_clusters[pair[1]][cluster] = identifier_clusters[pair[1]].get(cluster, 0) + 1
                

    uf.cluster_pair.clear()
    uf.pair_cluster.clear()

    largest_cluster = max(cluster_identifier, key=lambda c : len(cluster_identifier[c]))
    return cluster_identifier, identifier_clusters, largest_cluster, identifier_count
    

def generate_pairs(identifiers_a : list[str], identifiers_b : list[str]):
    pairs_list = []
    for identifier in identifiers_a:
        for signal in identifiers_b:
            if signal is not None:
                pairs_list.append((identifier, signal))
    for i in range(len(identifiers_a)):
        for j in range(i + 1, len(identifiers_a)):
            pairs_list.append((identifiers_a[i], identifiers_a[j]))

    return pairs_list

def is_identifier_check(identifiers : list[str], pair_element : str):
    for identfier in identifiers:
        if pair_element.startswith(identfier):
            return True
    return False