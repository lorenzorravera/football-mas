# Prediction Agent — training pipeline targets

.PHONY: help install ingest train-match-outcome train-all clean test inspect

export PYTHONPATH := $(PWD)/..:$(PYTHONPATH)

PYTHON := python3
DATA_DIR := data/raw
ARTEFACT_DIR := artefacts

help:
	@echo "Targets:"
	@echo "  install              - install Python dependencies"
	@echo "  inspect              - probe Aiven schema (read-only)"
	@echo "  ingest               - dump training data from Aiven to local parquet"
	@echo "  train-match-outcome  - train both Path A and Path B match outcome models"
	@echo "  train-all            - run all training pipelines"
	@echo "  test                 - smoke test inference wrappers"
	@echo "  clean                - remove generated data and artefacts"

install:
	$(PYTHON) -m pip install -r requirements.txt

inspect:
	$(PYTHON) -m scripts.inspect_aiven > aiven_schema_report.md
	@echo "Report written to aiven_schema_report.md"

ingest:
	@mkdir -p $(DATA_DIR)
	$(PYTHON) -m scripts.dump_to_parquet --output-dir $(DATA_DIR)

train-match-outcome:
	@mkdir -p $(ARTEFACT_DIR)
	$(PYTHON) -m scripts.train_match_outcome \
		--matches $(DATA_DIR)/matches.parquet \
		--output-dir $(ARTEFACT_DIR)

train-all: train-match-outcome

test:
	$(PYTHON) -m scripts.smoke_test

clean:
	rm -rf $(DATA_DIR) $(ARTEFACT_DIR)
