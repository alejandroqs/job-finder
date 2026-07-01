import json
import httpx
from typing import Union
from job_finder.interfaces import BaseEUFetcher

class EPSOFetcher(BaseEUFetcher):
    """
    Fetches job opportunities from the official European Data Portal (Hub Repository API).
    Queries the dataset metadata to locate and download the CSV resource.
    """
    
    API_URL = "https://data.europa.eu/api/hub/repo/datasets/job-opportunities"
    
    def __init__(self, api_url: str = API_URL):
        self.api_url = api_url

    def fetch_raw(self) -> bytes:
        """
        Queries Hub Repo dataset API, extracts the CSV download URL from distributions, and downloads it.
        
        Returns:
            The raw bytes of the CSV file.
        """
        # Step 1: Query Hub dataset metadata
        response = httpx.get(self.api_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        
        data = response.json()
        
        csv_url = None

        # Step 2: Try to extract from @graph format (Live API)
        if "@graph" in data:
            graph = data["@graph"]
            for item in graph:
                types = item.get("@type", [])
                if not isinstance(types, list):
                    types = [types]
                
                is_dist = any("distribution" in str(t).lower() for t in types)
                if not is_dist and "distribution" in item.get("@id", "").lower():
                    is_dist = True
                
                if is_dist:
                    fmt = item.get("dct:format", {})
                    fmt_id = ""
                    if isinstance(fmt, dict):
                        fmt_id = fmt.get("@id", "")
                    elif isinstance(fmt, str):
                        fmt_id = fmt
                    
                    has_csv = "csv" in fmt_id.lower()
                    if not has_csv:
                        for url_key in ["dcat:downloadURL", "dcat:accessURL"]:
                            url_val = item.get(url_key, {})
                            if isinstance(url_val, dict) and ".csv" in url_val.get("@id", "").lower():
                                has_csv = True
                                break
                            elif isinstance(url_val, str) and ".csv" in url_val.lower():
                                has_csv = True
                                break
                    
                    if has_csv:
                        for url_key in ["dcat:downloadURL", "dcat:accessURL"]:
                            url_val = item.get(url_key)
                            if isinstance(url_val, dict):
                                csv_url = url_val.get("@id")
                            elif isinstance(url_val, str):
                                csv_url = url_val
                            
                            if csv_url:
                                break
                if csv_url:
                    break

        # Step 3: Fallback to standard distributions array (Mock/CKAN API format)
        if not csv_url:
            distributions = data.get("distributions", [])
            if not isinstance(distributions, list):
                distributions = []
                
            for dist in distributions:
                fmt = dist.get("format", {})
                fmt_id = ""
                if isinstance(fmt, dict):
                    fmt_id = fmt.get("id", "")
                elif isinstance(fmt, str):
                    fmt_id = fmt
                    
                if fmt_id.lower() == "csv" or "csv" in fmt_id.lower():
                    for url_key in ["download_url", "access_url", "url"]:
                        urls = dist.get(url_key)
                        if isinstance(urls, list) and urls:
                            csv_url = urls[0]
                            break
                        elif isinstance(urls, str) and urls:
                            csv_url = urls
                            break
                if csv_url:
                    break
                    
        if not csv_url:
            raise ValueError("No CSV formatted resource found in EPSO Hub dataset distributions.")
            
        # Step 4: Stream and download the CSV resource content
        csv_response = httpx.get(csv_url, timeout=30.0, follow_redirects=True)
        csv_response.raise_for_status()
        
        return csv_response.content
