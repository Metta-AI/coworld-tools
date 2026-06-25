.PHONY: check build lib clean test test-nim test-python test-integration test-settlement audit-settlement benchmark

# CI gate for nim check - syncs deps first
check:
	./scripts/nim_check.sh

# Build the shared library
build lib:
	nimble buildLib

# Clean build artifacts
clean:
	rm -f libtribal_village.so libtribal_village.dylib libtribal_village.dll
	rm -f nim.cfg

# Run all tests
test: test-nim test-python

# Run Nim unit and integration tests (combined runner = single compilation, release = fast execution)
test-nim:
	nim r -d:release --path:src tests/run_all_tests.nim
	nim r -d:release --path:src tests/integration_behaviors.nim

# Run Python integration tests (requires lib to be built first)
test-python: lib
	pytest tests/test_python_integration.py -v

# Run full integration test suite
test-integration: lib
	nim r --path:src tests/integration_behaviors.nim
	pytest tests/test_python_integration.py -v -k "EndToEnd"

# Run settlement behavior tests
test-settlement:
	nim r --path:src tests/behavior_settlement.nim

# Audit settlement expansion metrics
audit-settlement:
	nim r -d:release --path:src scripts/audit_settlement.nim


# Benchmark: measure steps/second with perf regression instrumentation
benchmark:
	@mkdir -p baselines
	TV_PERF_SAVE_BASELINE=baselines/benchmark.json \
		nim c -r -d:release -d:perfRegression --path:src scripts/benchmark_steps.nim
