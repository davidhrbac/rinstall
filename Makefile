SHELL := /bin/bash
MAKEFLAGS += --no-print-directory

ENV ?= envs/example
PYTHON ?= python3
PYINFRA ?= pyinfra
TERRAFORM ?= terraform
ENV_ID := $(shell $(PYTHON) scripts/environment-id.py --env $(ENV)/env.yaml)
TF_INFRA_DIR := terraform/infra
BUILD_ENV_DIR := build/$(ENV_ID)
INFRA_TFVARS := $(BUILD_ENV_DIR)/infra.tfvars.json
TF_BACKEND_CONFIG ?=
TF_BACKEND_ARGS := $(addprefix -backend-config=,$(TF_BACKEND_CONFIG))
TF_INIT_ARGS ?=
TF_APPLY_ARGS ?=
PYINFRA_ARGS ?=
ADMIN_SSH_HOST ?=
ADMIN_SSH_CONFIG := $(BUILD_ENV_DIR)/$(ENV_ID).conf

.PHONY: help render-infra-vars ssh-config admin-ssh-config install-admin-ssh-config infra-init infra-fmt infra-validate infra-plan infra-apply infra-output destroy-commands bastion-configure node-prep rke2-install rke2-kubeconfig rancher-install rancher-install-run rancher-bootstrap rancher-bootstrap-run provision-all provision-all-yes verify

help:
	@printf '%s\n' 'Targets:'
	@printf '%s\n' '  provision-all       confirm, apply infra, run all phases, and print duration summary'
	@printf '%s\n' '  provision-all-yes   run provision-all without prompt'
	@printf '%s\n' ''
	@printf '\033[3m%s\033[0m\n' '  render-infra-vars   render build/<environment.id>/infra.tfvars.json from env.yaml'
	@printf '\033[3m%s\033[0m\n' '  ssh-config          render build/<environment.id>/ssh_config from env.yaml'
	@printf '\033[3m%s\033[0m\n' '  admin-ssh-config    render admin jump-host SSH fragment from env.yaml'
	@printf '\033[3m%s\033[0m\n' '  install-admin-ssh-config  upload the admin SSH fragment to the configured jump host'
	@printf '%s\n' '  infra-init          terraform init for infra layer'
	@printf '%s\n' '  infra-fmt           check Terraform formatting'
	@printf '%s\n' '  infra-validate      validate Terraform infra root'
	@printf '%s\n' '  infra-plan          plan vSphere infra using ENV=<env dir>'
	@printf '%s\n' '  infra-apply         apply vSphere infra using ENV=<env dir>'
	@printf '\033[3m%s\033[0m\n' '  infra-output        write Terraform outputs to build/<environment.id>/infra-output.json'
	@printf '%s\n' '  bastion-configure   configure dnsmasq/squid/routes on bastion1 with pyinfra'
	@printf '%s\n' '  node-prep           set hostnames/prompts on local nodes and prep Rancher nodes'
	@printf '%s\n' '  rke2-install        install RKE2 primary first, then join nodes'
	@printf '\033[3m%s\033[0m\n' '  rke2-kubeconfig     helper: fetch RKE2 kubeconfig and rewrite endpoint for bastion use'
	@printf '%s\n' '  rancher-install     install cert-manager and Rancher from bastion1 with pyinfra'
	@printf '%s\n' '  rancher-bootstrap   set Rancher runtime settings with pyinfra'
	@printf '%s\n' ''
	@printf '\033[3m%s\033[0m\n' '  destroy-commands    print explicit Terraform destroy commands for ENV=<env dir>'

render-infra-vars:
	$(PYTHON) scripts/render-infra-tfvars.py --env $(ENV)/env.yaml --out $(INFRA_TFVARS)

ssh-config:
	$(PYTHON) scripts/render-ssh-config.py --env $(ENV)/env.yaml --out $(BUILD_ENV_DIR)/ssh_config

admin-ssh-config:
	$(PYTHON) scripts/render-admin-ssh-config.py --env $(ENV)/env.yaml --out $(ADMIN_SSH_CONFIG)

install-admin-ssh-config: admin-ssh-config
	@set -euo pipefail; \
	admin_ssh_host="$(ADMIN_SSH_HOST)"; \
	if [[ -z "$$admin_ssh_host" ]]; then admin_ssh_host="$$($(PYTHON) scripts/admin-jump-host.py --env $(ENV)/env.yaml)"; fi; \
	ssh "$$admin_ssh_host" 'install -d -m 700 /root/.ssh/config.d'; \
	scp "$(ADMIN_SSH_CONFIG)" "$$admin_ssh_host:/root/.ssh/config.d/$(ENV_ID).conf"; \
	ssh "$$admin_ssh_host" 'chmod 600 /root/.ssh/config.d/$(ENV_ID).conf'; \
	printf 'Installed %s on %s:/root/.ssh/config.d/%s.conf\n' "$(ADMIN_SSH_CONFIG)" "$$admin_ssh_host" "$(ENV_ID)"; \
	printf '%s\n' 'Ensure /root/.ssh/config includes ~/.ssh/config.d/*.conf; this target does not modify it.'

infra-init:
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) init $(TF_BACKEND_ARGS) $(TF_INIT_ARGS)

infra-fmt:
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) fmt -check -recursive -diff

infra-validate:
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) validate

infra-plan: render-infra-vars
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) plan -var-file=../../$(INFRA_TFVARS)

infra-apply: render-infra-vars
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) apply $(TF_APPLY_ARGS) -var-file=../../$(INFRA_TFVARS)

infra-output:
	mkdir -p $(BUILD_ENV_DIR)
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) output -json > $(BUILD_ENV_DIR)/infra-output.json

destroy-commands:
	@$(PYTHON) scripts/render-infra-tfvars.py --env $(ENV)/env.yaml --out $(INFRA_TFVARS)
	@printf '%s\n' '============================================================'
	@printf '%s\n' 'Rancher Environment Terraform Destroy Commands'
	@printf '%s\n' '============================================================'
	@printf 'ENV:              %s\n' '$(ENV)'
	@printf 'Build dir:        %s\n' '$(BUILD_ENV_DIR)'
	@printf 'Terraform dir:    %s\n' '$(TF_INFRA_DIR)'
	@printf 'Tfvars:           %s\n' '$(INFRA_TFVARS)'
	@if [[ -n "$${TF_VAR_vsphere_server:-}" ]]; then printf 'vSphere server:   %s\n' "$$TF_VAR_vsphere_server"; else printf 'vSphere server:   %s\n' '(from tfvars or unset)'; fi
	@if [[ -n "$${TF_VAR_vsphere_user:-}" ]]; then printf 'vSphere user:     %s\n' "$$TF_VAR_vsphere_user"; else printf 'vSphere user:     %s\n' '(from tfvars or unset)'; fi
	@if [[ -n '$(TF_BACKEND_CONFIG)' ]]; then printf 'Backend config:   %s\n' '$(TF_BACKEND_CONFIG)'; fi
	@if [[ -n '$(TF_INIT_ARGS)' ]]; then printf 'Init args:        %s\n' '$(TF_INIT_ARGS)'; fi
	@printf '%s\n' '============================================================'
	@printf '%s\n' 'Review the destroy plan before running destroy.'
	@printf '%s\n' 'Confirm ENV, Terraform workspace/backend/state, and every planned deletion.'
	@printf '%s\n' ''
	@printf '%s\n' '1. Review plan:'
	@printf '%s\n' '$(TERRAFORM) -chdir=$(TF_INFRA_DIR) plan -destroy -var-file=../../$(INFRA_TFVARS)'
	@printf '%s\n' ''
	@printf '%s\n' '2. Destroy only after review:'
	@printf '%s\n' '$(TERRAFORM) -chdir=$(TF_INFRA_DIR) destroy -var-file=../../$(INFRA_TFVARS)'
	@printf '%s\n' '============================================================'

bastion-configure:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=bastion $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py

node-prep:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=node-prep $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py

rke2-install:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rke2-install-primary $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rke2-install-join $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py

rke2-kubeconfig:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rke2-kubeconfig $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py
	$(PYTHON) scripts/prepare-rke2-kubeconfig.py --env $(ENV)/env.yaml

rancher-install: rke2-kubeconfig rancher-install-run

rancher-install-run:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rancher-install $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py

rancher-bootstrap: rke2-kubeconfig rancher-bootstrap-run

rancher-bootstrap-run:
	ENV_CONFIG=$(ENV)/env.yaml PHASE=rancher-bootstrap $(PYINFRA) $(PYINFRA_ARGS) pyinfra/inventory.py pyinfra/deploy.py

provision-all:
	@set -euo pipefail; \
	format_duration() { \
	  local seconds=$$1; \
	  local hours=$$((seconds / 3600)); \
	  local minutes=$$(((seconds % 3600) / 60)); \
	  local remaining=$$((seconds % 60)); \
	  if ((hours > 0)); then \
	    printf '%dh %02dm %02ds' "$$hours" "$$minutes" "$$remaining"; \
	  elif ((minutes > 0)); then \
	    printf '%dm %02ds' "$$minutes" "$$remaining"; \
	  else \
	    printf '%ds' "$$remaining"; \
	  fi; \
	}; \
	run_phase() { \
	  local label=$$1; \
	  local target=$$2; \
	  local phase_start=$$SECONDS; \
	  printf '\n============================================================\n'; \
	  printf '==> %s\n' "$$label"; \
	  printf '============================================================\n'; \
	  if $(MAKE) "$$target" ENV="$(ENV)" PYTHON="$(PYTHON)" PYINFRA="$(PYINFRA)" PYINFRA_ARGS="$(PYINFRA_ARGS)" TERRAFORM="$(TERRAFORM)" TF_BACKEND_CONFIG="$(TF_BACKEND_CONFIG)" TF_INIT_ARGS="$(TF_INIT_ARGS)" TF_APPLY_ARGS="$(TF_APPLY_ARGS)"; then \
	    local duration=$$((SECONDS - phase_start)); \
	    completed_labels+=("$$label"); \
	    completed_durations+=("$$duration"); \
	  else \
	    local duration=$$((SECONDS - phase_start)); \
	    failed_phase=$$label; \
	    failed_duration=$$duration; \
	    return 1; \
	  fi; \
	}; \
	mode='interactive'; \
	if [[ "$(DEPLOY_YES)" == "1" ]]; then mode='noninteractive'; fi; \
	printf '============================================================\n'; \
	printf 'Rancher Environment Provisioning\n'; \
	printf '============================================================\n'; \
	printf 'ENV:              %s\n' "$(ENV)"; \
	printf 'Build dir:        %s\n' "$(BUILD_ENV_DIR)"; \
	printf 'Terraform dir:    %s\n' "$(TF_INFRA_DIR)"; \
	if [[ -n "$${TF_VAR_vsphere_server:-}" ]]; then printf 'vSphere server:   %s\n' "$$TF_VAR_vsphere_server"; else printf 'vSphere server:   %s\n' '(from tfvars or unset)'; fi; \
	if [[ -n "$${TF_VAR_vsphere_user:-}" ]]; then printf 'vSphere user:     %s\n' "$$TF_VAR_vsphere_user"; else printf 'vSphere user:     %s\n' '(from tfvars or unset)'; fi; \
	printf 'Mode:             %s\n' "$$mode"; \
	if [[ "$(DEPLOY_YES)" == "1" ]]; then \
	  printf 'Terraform apply:  %s\n' '$(TF_APPLY_ARGS)'; \
	  printf 'pyinfra:          %s\n' '$(PYINFRA_ARGS)'; \
	fi; \
	printf 'Phases:\n'; \
	printf '  1. Terraform apply\n'; \
	printf '  2. Bastion configure\n'; \
	printf '  3. Node prep\n'; \
	printf '  4. RKE2 install\n'; \
	printf '  5. Rancher install\n'; \
	printf '============================================================\n'; \
	if [[ "$(DEPLOY_YES)" != "1" ]]; then \
	  printf 'Run make infra-plan first if you have not reviewed the Terraform plan.\n'; \
	  printf 'Continue? [y/N] '; \
	  read -r reply; \
	  case "$$reply" in y|Y|yes|YES) ;; *) printf 'Aborted.\n'; exit 0 ;; esac; \
	fi; \
	completed_labels=(); \
	completed_durations=(); \
	failed_phase=''; \
	failed_duration=0; \
	total_start=$$SECONDS; \
	status=0; \
	run_phase 'Terraform apply' infra-apply || status=1; \
	if ((status == 0)); then run_phase 'Bastion configure' bastion-configure || status=1; fi; \
	if ((status == 0)); then run_phase 'Node prep' node-prep || status=1; fi; \
	if ((status == 0)); then run_phase 'RKE2 install' rke2-install || status=1; fi; \
	if ((status == 0)); then run_phase 'Rancher install' rancher-install || status=1; fi; \
	total_duration=$$((SECONDS - total_start)); \
	printf '\nDeployment summary for ENV=%s\n' "$(ENV)"; \
	if ((status == 0)); then printf 'Status: succeeded\n'; else printf 'Status: failed\n'; fi; \
	for index in "$${!completed_labels[@]}"; do \
	  printf '  %-20s %s\n' "$${completed_labels[$$index]}" "$$(format_duration "$${completed_durations[$$index]}")"; \
	done; \
	if ((status != 0)); then printf '  %-20s %s (failed)\n' "$$failed_phase" "$$(format_duration "$$failed_duration")"; fi; \
	printf '  %-20s %s\n' 'Total' "$$(format_duration "$$total_duration")"; \
	exit "$$status"

provision-all-yes:
	$(MAKE) provision-all DEPLOY_YES=1 ENV="$(ENV)" PYTHON="$(PYTHON)" PYINFRA="$(PYINFRA)" PYINFRA_ARGS="--yes" TERRAFORM="$(TERRAFORM)" TF_BACKEND_CONFIG="$(TF_BACKEND_CONFIG)" TF_INIT_ARGS="$(TF_INIT_ARGS)" TF_APPLY_ARGS="-auto-approve"

verify:
	$(PYTHON) -m py_compile lib/env_config.py lib/ssh_config.py pyinfra/inventory.py pyinfra/deploy.py scripts/admin-jump-host.py scripts/environment-id.py scripts/render-admin-ssh-config.py scripts/render-infra-tfvars.py scripts/render-ssh-config.py scripts/prepare-rke2-kubeconfig.py
	bash -n scripts/install-rke2.sh scripts/install-rancher.sh scripts/bootstrap-rancher.sh
	$(PYTHON) scripts/render-infra-tfvars.py --env $(ENV)/env.yaml --out $(INFRA_TFVARS)
	$(PYTHON) scripts/render-ssh-config.py --env $(ENV)/env.yaml --out $(BUILD_ENV_DIR)/ssh_config
	$(PYTHON) scripts/render-admin-ssh-config.py --env $(ENV)/env.yaml --out $(ADMIN_SSH_CONFIG)
	$(TERRAFORM) -chdir=$(TF_INFRA_DIR) fmt -check -recursive -diff
