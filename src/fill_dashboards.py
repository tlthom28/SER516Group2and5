# Python file to be ran in Docker container after main script completes

import requests
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# timeout for when the endpoint will be skipped
TIMEOUT = 200

# base url for api
base_url = "http://api:8080/"

# json payload for group 2's taiga metrics
G2_TAIGA_PAYLOAD = {
    "base_url": "",
    "slug": "jozefmak-t1e2018"
}

# json payload for group 5's WIP metrics
G5_WIP_PAYLOAD = {
    "taiga_url": "https://tree.taiga.io/project/lesly-we-play-sport/backlog"
}

# json payload for group 5's cycle time metrics
G5_CYCLE_PAYLOAD = {
    "slug": "lesly-we-play-sport",
    "start": "2025-01-01",
    "end": "2026-04-08"
}

# json payload for group 2's Github metrics
G2_GH_PAYLOAD = {
    "user": "TheAlgorithms",
    "repo": "Java",
    "branch": "master"
}

# json payload for group 5's Github metrics
G5_GH_PAYLOAD = {
    "repo_url": "https://github.com/pallets/flask.git",
    "start_date": "2026-03-01",
    "end_date": "2026-03-31"
}

def wait_for_health():
    # URL for API healthcheck
    url = f"{base_url}health"
    # max waiting time
    max_wait=60
    # how long to wait between requests in seconds
    interval=1
    elapsed=0
    print("Checking for API health...")
    while elapsed < max_wait:
        try:
            r = requests.get(url, timeout=2)
            if r.json().get("status") == "healthy":
                print("Healthy, running endpoints...")
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(interval)
        elapsed += interval
    print(f"API did not become healthy within {max_wait}s", file=sys.stderr)
    sys.exit(1)

def g2_class_coverage_run():
    r = requests.post(f"{base_url}metrics/class-coverage", 
                      json=G2_GH_PAYLOAD, timeout=TIMEOUT)

def g2_fog_index_run():
    r = requests.post(f"{base_url}metrics/fog-index",
                      json=G2_GH_PAYLOAD, timeout=TIMEOUT)
    
def g2_method_coverage_run():
    r = requests.post(f"{base_url}metrics/method-coverage",
                      json=G2_GH_PAYLOAD, timeout=TIMEOUT)

def g2_taiga_metrics_run():
    r = requests.post(f"{base_url}metrics/taiga-metrics",
                      json=G2_TAIGA_PAYLOAD, timeout=TIMEOUT)

def g5_wip_metrics_run():
    r = requests.post(f"{base_url}metrics/wip",
                      json=G5_WIP_PAYLOAD, timeout=TIMEOUT)

def g5_cycle_time_run():
    r = requests.get(f"{base_url}cycle-time",
                     params=G5_CYCLE_PAYLOAD, timeout=TIMEOUT)

def g5_gh_metrics_run():
    r = requests.post(f"{base_url}analyze",
                      json=G5_GH_PAYLOAD, timeout=TIMEOUT)

if __name__ == "__main__":
    # get health before starting, so server is ready
    wait_for_health()
    
    # all endpoints to be ran {name, method}
    endpoints = {
        "g2_class_coverage": g2_class_coverage_run,
        "g2_fog_index": g2_fog_index_run,
        "g2_method_coverage": g2_method_coverage_run,
        "g2_taiga_metrics": g2_taiga_metrics_run,
        "g5_gh_metrics": g5_gh_metrics_run,
        "g5_wip_metrics": g5_wip_metrics_run,
        "g5_cycle_time": g5_cycle_time_run,
    }
    
    # run endpoints concurrently so that none block each other
    with ThreadPoolExecutor() as ex:
        # submit each method to thread pool
        futures = {ex.submit(method): name for name, method in endpoints.items()}
        # for each future in the futures run method and return result
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                print(f"[OK] {name} ran")
            except Exception as e:
                print(f"[WARN] {name} failed", file=sys.stderr)