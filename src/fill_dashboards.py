# Python file to be ran in Docker container after main script completes

import requests
import time
import sys

# base url for api
base_url = "http://api:8080/"

# json payload for group 2's taiga metrics
G2_TAIGA_PAYLOAD = {
    "base_url": "",
    "slug": "jozefmak-t1e2018"
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

def class_coverage_run():
    r = requests.post(f"{base_url}metrics/class-coverage", json=G2_GH_PAYLOAD)

def fog_index_run():
    r = requests.post(f"{base_url}metrics/fog-index", json=G2_GH_PAYLOAD)
    
def method_coverage_run():
    r = requests.post(f"{base_url}metrics/method-coverage", json=G2_GH_PAYLOAD)

def g2_taiga_metrics_run():
    r = requests.post(f"{base_url}metrics/taiga-metrics",
                      json=G2_TAIGA_PAYLOAD)
    

def g5_gh_metrics_run():
    r = requests.post(f"{base_url}analyze", json=G5_GH_PAYLOAD)

if __name__ == "__main__":
    # get health before starting, so server is ready
    wait_for_health()
    
    # G2 metrics
    class_coverage_run()
    fog_index_run()
    method_coverage_run()
    g2_taiga_metrics_run()
    
    # G5 metrics
    g5_gh_metrics_run()
    # Not sure which metrics for taiga (if complete), please add here!