#!/bin/sh

# Add the backend directory to the Python path
export PYTHONPATH=$PYTHONPATH:$(pwd)/backend

# Clean up any old pytest cache folders that might cause permission issues
rm -rf .pytest_cache

# Install dependencies
pip3 install -r requirements.txt

# Run pytest without creating a cache folder
pytest -p no:cacheprovider --junitxml=testreport.xml --cov=backend --cov-report xml:coverage.xml --cov-report=html:coverage_report || if [ $? -eq 5 ]; then exit 0; else exit $?; fi