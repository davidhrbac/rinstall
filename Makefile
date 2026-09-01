SHELL := /bin/bash

ENV ?= envs/example
TF_INFRA_DIR := terraform/infra
BUILD_ENV_DIR := build/$(notdir $(ENV))
INFRA_TFVARS := $(BUILD_ENV_DIR)/infra.tfvars.json
PYTHON ?= python3
PYINFRA ?= pyinfra
TERRAFORM ?= terraform
TF_BACKEND_CONFIG ?=
TF_BACKEND_ARGS := $(addprefix -backend-config=,$(TF_BACKEND_CONFIG))
TF_INIT_ARGS ?=

.PHONY: help render-infra-vars ssh-config infra-init infra-fmt infra-validate infra-plan infra-apply infra-output bastion-configure node-prep rke2-install rancher-install rancher-bootstrap verify

help:
	@printf '%s\n' 'Targets:'
	@printf '%s\n' '  render-infra-vars   render build/<env>/infra.tfvars.json from env.yaml'
	@printf '%s\n' '  ssh-config          render build/<env>/ssh_config from env.yaml'
	@printf '%s\n' '  infra-init          terraform init for infra layer'
	@printf '%s\n' '                      requires TF_HTTP_ADDRESS or TF_BACKEND_CONFIG=<file>'
	@printf '%s\n' '  infra-fmt           check Terraform formatting'
	@printf '%s\n' '  infra-validate      validate Terraform infra root'
	@printf '%s\n' '  infra-plan          plan vSphere infra using ENV=<env dir>'
	@printf '%s\n' '  infra-apply         apply vSphere infra using ENV=<env dir>'
	@printf '%s\n' '  infra-output        write Terraform outputs to build/<env>/infra-output.json'
	@printf '%s\n' '  bastion-configure   configure dnsmasq/squid/routes on bastion1 with pyinfra'
	@printf '%s\n' '  node-prep           set hostnames/prompts on local nodes and prep Rancher nodes'
	@printf '%s\n' '  rke2-install        install RKE2 primary first, then join nodes'
	@printf '%s\n' '  rancher-install     install cert-manager and Rancher from bastion1 with pyinfra'
	@printf '%s\n' '  rancher-bootstrap   set Rancher runtime settings with pyinfra'

render-infra-vars:
	$(PYTHON) scripts/render-infra-tfvars.py --env $(ENV)/env.yaml --out $(INFRA_TFVARS)

ssh-config:
	$(PYTHON) scripts/render-ssh-config.py --env $(ENV)/env.yaml --out $(BUILD_ENV_DIR)/ssh_config

infra-init:
	@if [[ -z "$${TF_HTTP_ADDRESS:-}" && -z "$(TF_BACKEND_CONFIG)" && "$(TF_INIT_ARGS)" != *"-backend=false"* ]]; then \
		printf '%s\n' 'missing Terraform HTTP backend address'; \
		printf '%s\n' 'Set TF_HTTP_ADDRESS in .envrc, run: make infra-init TF_BACKEND_CONFIG=<backend-config-file>, or use TF_INIT_ARGS=-backend=false for local validation only.'; \
		exit 2; \
	fi
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) init $(TF_BACKEND_ARGS) $(TF_INIT_ARGS)

infra-fmt:
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) fmt -check -recursive -diff

infra-validate:
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) validate

infra-plan: render-infra-vars
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) plan -var-file=../../$(INFRA_TFVARS)

infra-apply: render-infra-vars
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) apply -var-file=../../$(INFRA_TFVARS)

infra-output:
	mkdir -p $(BUILD_ENV_DIR)
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) output -json > $(BUILD_ENV_DIR)/infra-output.json

bastion-configure:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=bastion $(PYINFRA) pyinfra/inventory.py pyinfra/deploy.py

node-prep:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=node-prep $(PYINFRA) pyinfra/inventory.py pyinfra/deploy.py

rke2-install:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rke2-install-primary $(PYINFRA) pyinfra/inventory.py pyinfra/deploy.py
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rke2-install-join $(PYINFRA) pyinfra/inventory.py pyinfra/deploy.py

rancher-install:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rancher-install $(PYINFRA) pyinfra/inventory.py pyinfra/deploy.py

rancher-bootstrap:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rancher-bootstrap $(PYINFRA) pyinfra/inventory.py pyinfra/deploy.py

verify:
	$(PYTHON) -m py_compile lib/env_config.py lib/ssh_config.py pyinfra/inventory.py pyinfra/deploy.py scripts/render-infra-tfvars.py scripts/render-ssh-config.py
	bash -n scripts/install-rke2.sh scripts/install-rancher.sh scripts/bootstrap-rancher.sh
	$(PYTHON) scripts/render-infra-tfvars.py --env $(ENV)/env.yaml --out $(INFRA_TFVARS)
	$(PYTHON) scripts/render-ssh-config.py --env $(ENV)/env.yaml --out $(BUILD_ENV_DIR)/ssh_config
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) fmt -check -recursive -diff
