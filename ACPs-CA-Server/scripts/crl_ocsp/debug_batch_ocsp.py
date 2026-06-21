#!/usr/bin/env python3

"""Debug script to test the batch OCSP endpoint directly"""

import requests

# Test the batch OCSP endpoint directly
url = "http://localhost:8003/api/v1/ocsp/batch"

test_data = {
    "certificates": [
        {
            "serial_number": "VALID0005D7D1753",
            "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
        },
        {
            "serial_number": "EXPIRED08A80C61",
            "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
        },
        {
            "serial_number": "NONEXISTENT123456",
            "issuer_key_hash": "d042ee4e30dcd77e3a2f8eb3f5d8fe8673567864",
        },
    ]
}

try:
    response = requests.post(url, json=test_data)
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers: {response.headers}")
    print(f"Response Content: {response.text}")
except Exception as e:
    print(f"Error: {e}")
