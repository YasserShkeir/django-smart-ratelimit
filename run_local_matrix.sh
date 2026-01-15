#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
PARALLEL=false
for arg in "$@"; do
    case $arg in
        --parallel|-p)
            PARALLEL=true
            shift
            ;;
    esac
done

echo "Started Local Matrix Testing..."
if [ "$PARALLEL" = true ]; then
    echo -e "${BLUE}Running in PARALLEL mode${NC}"
fi

# Ensure we are in the root directory
if [ ! -f "docker-compose.qa.yml" ]; then
    echo -e "${RED}Error: docker-compose.qa.yml not found. Please run this script from the project root.${NC}"
    exit 1
fi

# 1. Start Environment
echo "Building and starting Docker environment..."
docker compose -f docker-compose.qa.yml up -d --build

echo "Waiting for services to become healthy..."
# Give containers a moment to boot and run migrations/setup
sleep 15

# Define Test Matrix
# Format: "Service Name|Port|Description"
TESTS=(
    "memory|8001|Memory Backend"
    "redis|8002|Redis Backend"
    "redis-async|8003|Async Redis Backend"
    "mongodb|8004|MongoDB Backend"
    "multi|8005|Multi-Backend (Redis + Memory)"
)

# Create temp directory for results
RESULTS_DIR=$(mktemp -d)
trap "rm -rf $RESULTS_DIR" EXIT

# Function to run a single test
run_test() {
    local BACKEND=$1
    local PORT=$2
    local DESC=$3
    local LOG_FILE="$RESULTS_DIR/${BACKEND}.log"
    local RESULT_FILE="$RESULTS_DIR/${BACKEND}.result"

    {
        echo -e "\n--------------------------------------------------"
        echo -e "Testing: ${DESC}"
        echo -e "Target: http://localhost:${PORT}"
        echo -e "--------------------------------------------------"

        # Run the test
        if python3 tests/test_project/verify_scenarios.py --url http://localhost:${PORT} 2>&1; then
            echo "PASS" > "$RESULT_FILE"
            echo -e "${GREEN}[PASS] ${DESC}${NC}"
        else
            echo "FAIL" > "$RESULT_FILE"
            echo -e "${RED}[FAIL] ${DESC}${NC}"
        fi
    } 2>&1 | tee "$LOG_FILE"
}

if [ "$PARALLEL" = true ]; then
    # Parallel execution with live output
    echo -e "\n${YELLOW}Starting parallel test execution...${NC}"

    PIDS=()
    for test in "${TESTS[@]}"; do
        IFS="|" read -r BACKEND PORT DESC <<< "$test"
        run_test "$BACKEND" "$PORT" "$DESC" &
        PIDS+=($!)
    done

    # Wait for all background jobs
    echo -e "${BLUE}Waiting for all tests to complete...${NC}"
    for pid in "${PIDS[@]}"; do
        wait $pid 2>/dev/null || true
    done

    # Collect results
    echo -e "\n${YELLOW}=================================================${NC}"
    echo -e "${YELLOW}                  FINAL RESULTS                   ${NC}"
    echo -e "${YELLOW}=================================================${NC}"

    FAILED=0
    for test in "${TESTS[@]}"; do
        IFS="|" read -r BACKEND PORT DESC <<< "$test"
        RESULT_FILE="$RESULTS_DIR/${BACKEND}.result"
        if [ -f "$RESULT_FILE" ] && [ "$(cat $RESULT_FILE)" = "PASS" ]; then
            echo -e "${GREEN}✓ ${DESC}${NC}"
        else
            echo -e "${RED}✗ ${DESC}${NC}"
            FAILED=1
        fi
    done
else
    # Sequential execution (original behavior)
    FAILED=0
    for test in "${TESTS[@]}"; do
        IFS="|" read -r BACKEND PORT DESC <<< "$test"

        echo -e "\n--------------------------------------------------"
        echo -e "Testing: ${DESC}"
        echo -e "Target: http://localhost:${PORT}"
        echo -e "--------------------------------------------------"

        # Flush Redis to ensure clean state for tests sharing the Redis service
        docker compose -f docker-compose.qa.yml exec -T redis redis-cli FLUSHALL > /dev/null 2>&1 || true

        # Temporarily turn off 'set -e' so a single failure doesn't abort the whole script
        set +e
        python3 tests/test_project/verify_scenarios.py --url http://localhost:${PORT}
        RESULT=$?
        set -e

        if [ $RESULT -eq 0 ]; then
            echo -e "${GREEN}[PASS] ${DESC}${NC}"
        else
            echo -e "${RED}[FAIL] ${DESC}${NC}"
            FAILED=1
        fi
    done
fi

echo -e "\n--------------------------------------------------"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All local matrix tests PASSED!${NC}"
    exit 0
else
    echo -e "${RED}Some tests FAILED. Check output above.${NC}"
    exit 1
fi
