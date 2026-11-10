from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from evalith.api import create_app
from evalith.config import Settings

SECRET_ENV = "OPENAI_API_KEY=sk-env-secret-123456"
SECRET_FILE = "token=sk-file-secret-abcdef"


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-project"
    (root / "docs").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "secrets").mkdir()
    (root / ".git").mkdir()
    (root / "README.md").write_text(
        "# Approval Agent\n\nThis project runs a release approval agent.\n"
        "Only a release manager may publish an artifact.\n",
        encoding="utf-8",
    )
    (root / "docs" / "RELEASE_POLICY.md").write_text(
        "# Release policy\n\nA contributor may propose a release; only the release manager may publish.\n",
        encoding="utf-8",
    )
    (root / "docs" / "internal").mkdir()
    (root / "docs" / "internal" / "plan.md").write_text(
        "# Internal plan\nDo not send this outside the approved scope.\n",
        encoding="utf-8",
    )
    (root / "src" / "agent.py").write_text(
        "def can_publish(actor_role: str) -> bool:\n"
        "    return actor_role == 'release_manager'\n",
        encoding="utf-8",
    )
    (root / ".env").write_text(SECRET_ENV + "\n", encoding="utf-8")
    (root / "secrets" / "credentials.txt").write_text(SECRET_FILE + "\n", encoding="utf-8")
    (root / "notes.txt").write_text(
        'API_KEY = "sk-inline-secret-value"\n'
        "OPENAI_API_KEY=sk-prefixed-secret\n"
        "DB_PASSWORD=db-prefixed-secret\n"
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLESECRET\n"
        "AWS_SECRET_ACCESS_KEY=synthetic-secret-value\n"
        "JWT_SECRET_KEY=synthetic-signing-secret\n"
        'PRIVATE_KEY = "raw-private-key-value"\n'
        'GITHUB_PAT=github_pat_examplecredential\n'
        "VAULT_TOKEN=hvs.syntheticVaultToken\n"
        "The agent approves releases.\n",
        encoding="utf-8",
    )
    (root / "basic-auth.txt").write_text(
        'const basicAuth = "Basic dXNlcjpwYXNz";\n', encoding="utf-8"
    )
    (root / "bearer-token.txt").write_text(
        "Authorization: Bearer abc/def+ghi==\n", encoding="utf-8"
    )
    (root / ".git-credentials").write_text(
        "https://ghp_syntheticGitToken@github.com\n", encoding="utf-8"
    )
    (root / ".yarnrc.yml").write_text(
        'npmAuthToken: "registry-secret-value"\n', encoding="utf-8"
    )
    (root / "config").mkdir()
    (root / "config" / "alias.yaml").write_text(
        "shared: &dbpass hunter2\npassword: *dbpass\n"
        "blockshared: &pw |\n  synthetic-anchor-block-secret\n"
        "password: *pw\n"
        "keyvalue: &value ordinary-secret\n"
        "api_key: *value\n"
        "servicevalue: &service hunter2\n"
        "servicePassword: *service\n",
        encoding="utf-8",
    )
    (root / "config" / "secret.json").write_text(
        '{"kind": "Secret", "stringData": {"value": "synthetic-json-secret"}}\n',
        encoding="utf-8",
    )
    (root / "config" / "flow-brace-secret.yaml").write_text(
        'kind: Secret\ndata: {first: "}", second: "synthetic-flow-brace"}\n',
        encoding="utf-8",
    )
    (root / "config" / "json-env.json").write_text(
        '{"env": [{"name": "PASSWORD", "value": "synthetic-json-env"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "quoted-flow-env.yaml").write_text(
        'env: [{"name": "API_KEY", "value": "synthetic-quoted-flow-env"}]\n',
        encoding="utf-8",
    )
    (root / "config" / "flow-alias-secret.yaml").write_text(
        "shared: &values {foo: synthetic-flow-alias-secret}\n"
        "secret: {kind: Secret, data: *values}\n",
        encoding="utf-8",
    )
    (root / "config" / "reused-anchor-env.yaml").write_text(
        "a: &entry {name: MODE}\nb: &entry {name: DB_PASSWORD}\n"
        "env: [{<<: *entry, value: synthetic-reused-anchor}]\n",
        encoding="utf-8",
    )
    (root / "config" / "transitive-merge-env.yaml").write_text(
        "a: &base {name: DB_PASSWORD}\nb: &entry {<<: *base}\n"
        "env: [{<<: *entry, value: synthetic-transitive-merge}]\n",
        encoding="utf-8",
    )
    (root / "config" / "prefixed-pass-env.yaml").write_text(
        "env:\n  - name: DB_PASS\n    value: synthetic-prefixed-pass\n"
        "  - name: APP_DB_PASS\n    value: synthetic-app-prefixed-pass\n"
        "  - name: DB_PWD\n    value: synthetic-prefixed-pwd\n",
        encoding="utf-8",
    )
    (root / "config" / "prefixed-pass-env.json").write_text(
        '{"env": [{"name": "DB_PASS", "value": '
        '"synthetic-json-prefixed-pass"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "merge-sequence-block-env.yaml").write_text(
        "template: &entry {name: DB_PASSWORD}\nenv:\n"
        "  - <<: [*entry]\n    value: synthetic-merge-sequence-block\n",
        encoding="utf-8",
    )
    (root / "config" / "merge-sequence-flow-env.yaml").write_text(
        "template: &entry {name: DB_PASSWORD}\n"
        "env: [{<<: [*entry], value: synthetic-merge-sequence-flow}]\n",
        encoding="utf-8",
    )
    (root / "config" / "flow-anchor-block-env.yaml").write_text(
        "defaults: &entry {name: DB_PASSWORD}\nenv:\n"
        "  - <<: *entry\n    value: synthetic-flow-anchor-block\n",
        encoding="utf-8",
    )
    (root / "config" / "dotted-anchor-env.yaml").write_text(
        "label: &env.name DB_PASSWORD\nenv:\n"
        "- name: *env.name\n  value: synthetic-dotted-anchor\n",
        encoding="utf-8",
    )
    (root / "config" / "nested-name-alias-env.yaml").write_text(
        "label: &env.name DB_PASSWORD\n"
        "defaults: &entry {name: *env.name}\nenv:\n"
        "  - <<: *entry\n    value: synthetic-nested-name-alias\n",
        encoding="utf-8",
    )
    (root / "config" / "mapping-key-anchor-env.yaml").write_text(
        "defaults: &entry\n  name: DB_PASSWORD\nenv:\n"
        "  - <<: *entry\n    value: synthetic-mapping-key-anchor\n",
        encoding="utf-8",
    )
    (root / "config" / "comment-anchor-env.yaml").write_text(
        "# &v example\nshared: &v synthetic-comment-anchor\n"
        "env:\n- name: DB_PASSWORD\n  value: *v\n",
        encoding="utf-8",
    )
    (root / "config" / "access-key-env.yaml").write_text(
        "env:\n  - name: ACCESS_KEY\n    value: synthetic-access-key-block\n",
        encoding="utf-8",
    )
    (root / "config" / "access-key-flow.yaml").write_text(
        "env: [{name: ACCESS_KEY, value: synthetic-access-key-flow}]\n",
        encoding="utf-8",
    )
    (root / "config" / "access-key-env.json").write_text(
        '{"env": [{"name": "ACCESS_KEY", "value": '
        '"synthetic-access-key-json"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "merge-alias-env.yaml").write_text(
        "defaults: &entry {name: DB_PASSWORD}\n"
        "shared: &pw synthetic-merge-alias-anchor\n"
        "env: [{<<: *entry, value: *pw}]\n",
        encoding="utf-8",
    )
    (root / "config" / "flow-merge-env.yaml").write_text(
        "defaults: &entry {name: DB_PASSWORD}\n"
        "env: [{<<: *entry, value: synthetic-flow-merge}]\n",
        encoding="utf-8",
    )
    (root / "config" / "flow-alias-kind-secret.yaml").write_text(
        "x-kind: &k Secret\nshared: &d {foo: c2VjcmV0LWZsb3ctYWxpYXM=}\n"
        "resource: {kind: *k, data: *d}\n",
        encoding="utf-8",
    )
    (root / "config" / "merge-env.yaml").write_text(
        "env:\n  - &entry\n    name: DB_PASSWORD\n"
        "    value: synthetic-merge-first\n  - <<: *entry\n"
        "    value: synthetic-merge-second\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged-block-name-env.yaml").write_text(
        "env:\n  - name: !!str >-\n      DB_PASSWORD\n"
        "    value: synthetic-tagged-block-name\n",
        encoding="utf-8",
    )
    (root / "config" / "reordered-block-name-env.yaml").write_text(
        "env:\n  - value: synthetic-reordered-block-name\n"
        "    name: >-\n      OPENAI_API_KEY\n",
        encoding="utf-8",
    )
    (root / "config" / "later-kind-alias-secret.yaml").write_text(
        "x-kind: &k Secret\nkind: *k\ndata:\n"
        "  config: c3ludGhldGljLWxhdGVyLWtpbmQ=\nlater: &k ConfigMap\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged-anchor-kind-secret.yaml").write_text(
        "type: &k !!str Secret\nkind: *k\nstringData:\n"
        "  payload: synthetic-tagged-anchor-kind\n",
        encoding="utf-8",
    )
    (root / "config" / "yaml-secret-annotation.yaml").write_text(
        "kind: Secret\nmetadata:\n  annotations:\n"
        "    kubectl.kubernetes.io/last-applied-configuration: "
        "'{\"kind\":\"Secret\",\"data\":{\"config\":\"c3ludGhldGljLXlhbWw=\"}}'\n"
        "stringData:\n  value: synthetic-yaml-annotation\n",
        encoding="utf-8",
    )
    (root / "config" / "later-anchor-env.yaml").write_text(
        "label: &n DB_PASSWORD\nenv:\n- name: *n\n"
        "  value: synthetic-later-anchor\nlater: &n PORT\n",
        encoding="utf-8",
    )
    (root / "config" / "anchor-comment-env.yaml").write_text(
        "label: &n DB_PASSWORD\n# &n PORT\nenv:\n- name: *n\n"
        "  value: synthetic-anchor-comment\n",
        encoding="utf-8",
    )
    inner = {
        "kind": "Secret",
        "data": {"config": "c3ludGhldGljLWFubm90YXRpb24="},
    }
    (root / "config" / "secret-annotation.json").write_text(
        json.dumps(
            {
                "kind": "Secret",
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": json.dumps(inner)
                    }
                },
                "data": {"x": "eA=="},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged-anchor-env.yaml").write_text(
        "label: &n !!str DB_PASSWORD\nenv:\n- name: *n\n"
        "  value: synthetic-tagged-anchor\n",
        encoding="utf-8",
    )
    (root / "config" / "block-name-env.yaml").write_text(
        "env:\n  - name: >-\n      DB_PASSWORD\n"
        "    value: synthetic-block-name\n",
        encoding="utf-8",
    )
    (root / "config" / "apostrophe-env.yaml").write_text(
        "description: user's agent\n"
        "env: [{name: DB_PASSWORD, value: synthetic-apostrophe-env}]\n",
        encoding="utf-8",
    )
    (root / "config" / "reordered-name-alias-env.yaml").write_text(
        "label: &n DB_PASSWORD\nenv:\n- value: synthetic-reordered-alias\n"
        "  name: *n\n",
        encoding="utf-8",
    )
    (root / "config" / "name-alias-env.yaml").write_text(
        "label: &n DB_PASSWORD\nenv:\n- name: *n\n"
        "  value: synthetic-name-alias\n",
        encoding="utf-8",
    )
    (root / "config" / "name-comment-env.yaml").write_text(
        "env: [{name: DB_PASSWORD # production\n"
        ", value: synthetic-name-comment}]\n",
        encoding="utf-8",
    )
    (root / "config" / "comment-brace-end-env.yaml").write_text(
        "env: [{name: DB_PASSWORD, # }\n"
        "  value: synthetic-comment-brace-end}]\n",
        encoding="utf-8",
    )
    (root / "config" / "escaped-env-keys.yaml").write_text(
        'env:\n  - "\\u006eame": OPENAI_API_KEY\n'
        '    "\\u0076alue": synthetic-escaped-env-key\n',
        encoding="utf-8",
    )
    (root / "config" / "multiline-flow-env.yaml").write_text(
        "env: [{name: SMTP_PASSWORD,\n  value: synthetic-multiline-flow}]\n"
        "extra_flow: [{\n  name: DB_PASSWORD,\n  value: synthetic-multiline-db\n}]\n",
        encoding="utf-8",
    )
    (root / "config" / "comment-brace-env.yaml").write_text(
        "# don't\nenv: [{name: API_KEY, value: synthetic-comment-brace}]\n",
        encoding="utf-8",
    )
    (root / "config" / "escaped-flow-alias-env.yaml").write_text(
        'shared: &v synthetic-escaped-flow-alias\nenv: '
        '[{name: "API\\u005fKEY", value: *v}]\n',
        encoding="utf-8",
    )
    (root / "config" / "quoted-brace-env.yaml").write_text(
        'container: {marker: "{", env: [{name: PASSWORD, '
        'value: synthetic-quoted-brace-env}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "x-escape-kind-secret.yaml").write_text(
        'kind: "Sec\\x72et"\nstringData:\n  neutral: synthetic-x-escape\n',
        encoding="utf-8",
    )
    (root / "config" / "nested-flow-env.yaml").write_text(
        '{env: [{name: API_KEY, value: synthetic-nested-flow}, '
        '{name: APP_NAME, value: ordinary}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "multi-json-env.json").write_text(
        '{"env": [{"name": "PASSWORD", "value": "synthetic-json-alpha"}, '
        '{"name": "API_KEY", "value": "synthetic-json-beta"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "vendor-env.yaml").write_text(
        "- name: SENDGRID_API_KEY\n  value: synthetic-sendgrid\n"
        "- name: TWILIO_AUTH_TOKEN\n  value: synthetic-twilio\n",
        encoding="utf-8",
    )
    (root / "config" / "alias-env.yaml").write_text(
        "shared: &v synthetic-alias-env\nenv:\n"
        "- name: API_KEY\n  value: *v\n"
        "env: [{name: API_KEY, value: *v}]\n",
        encoding="utf-8",
    )
    (root / "config" / "flow-brace-env.yaml").write_text(
        'env: [{name: PASSWORD, value: "abc{synthetic-flow-brace-env}xyz"}]\n',
        encoding="utf-8",
    )
    (root / "config" / "nested-env.yaml").write_text(
        "containers:\n- name: app\n  env:\n"
        "  - value: synthetic-nested-env\n    name: PASSWORD\n",
        encoding="utf-8",
    )
    (root / "config" / "smtp-env.yaml").write_text(
        "- name: SMTP_PASSWORD\n  value: synthetic-smtp-env\n",
        encoding="utf-8",
    )
    (root / "config" / "smtp-env.json").write_text(
        '{"env": [{"name": "REDIS_PASSWORD", '
        '"value": "synthetic-redis-json"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "quoted-env.yaml").write_text(
        'env:\n  - "name": AWS_SECRET_ACCESS_KEY\n'
        '    "value": synthetic-quoted-env\n',
        encoding="utf-8",
    )
    (root / "config" / "eof-reordered-env.yaml").write_text(
        "env:\n- value: synthetic-eof-reordered\n  name: PASSWORD",
        encoding="utf-8",
    )
    (root / "config" / "aws-session-env.yaml").write_text(
        "- name: AWS_SESSION_TOKEN\n  value: synthetic-aws-session\n",
        encoding="utf-8",
    )
    (root / "config" / "aws-session-env.json").write_text(
        '{"env": [{"name": "AWS_SESSION_TOKEN", '
        '"value": "synthetic-aws-session-json"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "blank-env.yaml").write_text(
        "env:\n  - name: API_KEY\n\n    value: synthetic-blank-env\n",
        encoding="utf-8",
    )
    (root / "config" / "prefixed-env.yaml").write_text(
        "- name: PROD_DB_PASSWORD\n  value: synthetic-prefixed-env\n",
        encoding="utf-8",
    )
    (root / "config" / "prefixed-env.json").write_text(
        '{"env": [{"name": "PROD_DB_PASSWORD", '
        '"value": "synthetic-prefixed-json"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "escaped-env.yaml").write_text(
        '- name: "API\\u005fKEY"\n  value: synthetic-escaped-env\n'
        '- name: "API\\u005fKEY"\n  value: synthetic-escaped-flow\n',
        encoding="utf-8",
    )
    (root / "config" / "application.properties").write_text(
        "db.password synthetic-java-properties\n"
        "pass\\u0077ord=synthetic-escaped-property\n"
        "pass\\u0077ord: synthetic-colon-property\n"
        "password=\\\n  synthetic-continued-property\n",
        encoding="utf-8",
    )
    (root / "config" / "embedded.json.md").write_text(
        '```json\n{ "\\u0070assword": "synthetic-embedded-json" }\n```\n',
        encoding="utf-8",
    )
    (root / "config" / "backup.asc").write_text(
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
        "synthetic-pgp-private-key\n"
        "-----END PGP PRIVATE KEY BLOCK-----\n",
        encoding="utf-8",
    )
    (root / "config" / "aws-env.yaml").write_text(
        "- name: AWS_ACCESS_KEY_ID\n  value: synthetic-aws-key-id\n"
        "- name: AWS_SECRET_ACCESS_KEY\n  value: synthetic-aws-secret\n",
        encoding="utf-8",
    )
    (root / "config" / "aws-env.json").write_text(
        '{"env": [{"name": "AWS_SECRET_ACCESS_KEY", '
        '"value": "synthetic-aws-json-secret"}]}\n',
        encoding="utf-8",
    )
    (root / "config" / "tagged-env.yaml").write_text(
        "- name: !!str PASSWORD\n  value: synthetic-tagged-env\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged-escaped-secret.yaml").write_text(
        'kind: !!str "Se\\u0063ret"\nstringData:\n  foo: synthetic-tagged-escaped\n',
        encoding="utf-8",
    )
    (root / "config" / "escaped-attribute.xml").write_text(
        '<property name="pass&#119;ord" value="synthetic-escaped-attribute"/>\n',
        encoding="utf-8",
    )
    (root / "config" / "tagged-block-kind-secret.yaml").write_text(
        "kind: !!str |-\n  Secret\nstringData: {foo: synthetic-tagged-block}\n",
        encoding="utf-8",
    )
    (root / "config" / "crlf-secret.yaml").write_bytes(
        b"kind: Secret\r\nstringData:\r\n  db: synthetic-crlf-secret\r\n"
    )
    (root / "config" / "tagged-data-secret.yaml").write_text(
        "kind: Secret\n!!str data:\n  foo: synthetic-tagged-data-secret\n",
        encoding="utf-8",
    )
    (root / "config" / "no-newline-secret.yaml").write_text(
        "kind: Secret\ndata: {username: synthetic-no-newline-secret}",
        encoding="utf-8",
    )
    (root / "config" / "escaped-kind-key-secret.yaml").write_text(
        '"k\\u0069nd": Secret\nstringData:\n'
        "  neutral: synthetic-escaped-kind-key\n",
        encoding="utf-8",
    )
    (root / "config" / "escaped-data-key-secret.yaml").write_text(
        'kind: Secret\n"\\u0064ata":\n  foo: synthetic-escaped-data-key\n',
        encoding="utf-8",
    )
    (root / "config" / "spaced-key-secret.yaml").write_text(
        "kind: Secret\nstringData :\n  foo: synthetic-spaced-key-secret\n",
        encoding="utf-8",
    )
    (root / "config" / "escaped-kind-secret.yaml").write_text(
        'kind: "\\u0053ecret"\ndata: {config: synthetic-escaped-kind-secret}\n',
        encoding="utf-8",
    )
    (root / "config" / "block-anchor-secret.yaml").write_text(
        "shared: &creds\n  neutral: synthetic-block-anchor-secret\n"
        "kind: Secret\ndata: *creds\n"
        "extra_anchor: &creds2\n  neutral: synthetic-block-stringdata\n"
        "kind: Secret\nstringData: *creds2\n",
        encoding="utf-8",
    )
    (root / "config" / "block-kind-secret.yaml").write_text(
        "kind: >-\n  Secret\nstringData:\n  value: synthetic-block-kind-secret\n",
        encoding="utf-8",
    )
    (root / "config" / "anchored-data-secret.yaml").write_text(
        "kind: Secret\nmetadata: {labels: &payload {foo: c2VjcmV0}}\n"
        "data: *payload\n",
        encoding="utf-8",
    )
    (root / "config" / "alias-secret.yaml").write_text(
        "x-kind: &k Secret\nkind: *k\ndata:\n  value: synthetic-alias-secret\n",
        encoding="utf-8",
    )
    (root / "config" / "flow-env.yaml").write_text(
        "env: [{name: API_KEY, value: synthetic-flow-env}]\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged-secret.yaml").write_text(
        "kind: !!str Secret\ndata:\n  config: synthetic-tagged-secret-data\n"
        "{kind: !!str Secret, stringData: {foo: synthetic-tagged-flow-secret}}\n"
        "kind: &secret_kind Secret\nstringData:\n"
        "  config: synthetic-anchored-secret\n"
        "---\nkind: Secret\ndata:\n\n"
        "  database: c2VjcmV0LXN5bnRoZXRpYw==\n",
        encoding="utf-8",
    )
    (root / "config" / "flow-secret.yaml").write_text(
        "{kind: Secret, stringData: {foo: synthetic-flow-secret}}\n"
        '{"kind": Secret, "data": {foo: synthetic-quoted-flow-secret}}\n',
        encoding="utf-8",
    )
    (root / "config" / "value-first-env.yaml").write_text(
        "env:\n- value: synthetic-value-first\n  name: PASSWORD\n"
        "- name: API_KEY # comment\n  value: synthetic-comment-name\n",
        encoding="utf-8",
    )
    (root / "config" / "quoted-data-secret.yaml").write_text(
        'kind: Secret\n"stringData":\n  value: synthetic-quoted-data-secret\n',
        encoding="utf-8",
    )
    (root / "config" / "list-secret.yaml").write_text(
        "items:\n- kind: Secret\n  stringData:\n"
        "    value: synthetic-list-secret\n",
        encoding="utf-8",
    )
    (root / "config" / "commented-secret.yaml").write_text(
        "kind: Secret # deployment credential\n"
        "data:\n  connection: synthetic-comment-secret-data\n",
        encoding="utf-8",
    )
    (root / "config" / "quoted-secret.yaml").write_text(
        'kind: "Secret"\nstringData:\n  value: synthetic-quoted-secret\n',
        encoding="utf-8",
    )
    (root / "config" / "k8s-env.yaml").write_text(
        "env:\n  - name: DATABASE_PASSWORD\n    value: arbitrary-secret\n"
        "  - name: API_KEY\n    value: |\n      synthetic-multiline-env\n"
        "kind: Secret\ndata:\n  db: synthetic-secret-data\n",
        encoding="utf-8",
    )
    (root / "config" / "kube.yaml").write_text(
        "client-key-data: c2VjcmV0LXN5bnRoZXRpYw==", encoding="utf-8"
    )
    (root / "config" / "npm-token.txt").write_text(
        "npm_0123456789abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8"
    )
    (root / "config" / "stripe.txt").write_text(
        "new Stripe('rk_live_exampleStripeKey123')\n", encoding="utf-8"
    )
    (root / "config" / "gitlab.txt").write_text(
        "token=glpat-examplegitlabtoken\n", encoding="utf-8"
    )
    (root / "config" / "classic-token.txt").write_text(
        "token=ghp_exampleclassictoken\n", encoding="utf-8"
    )
    (root / "config" / "sas.txt").write_text(
        "https://example.blob.core.windows.net/container/blob?"
        "sv=2023-01-03&sig=SYNTHETIC-SAS-VALUE\n",
        encoding="utf-8",
    )
    (root / "config" / "azure.txt").write_text(
        "DefaultEndpointsProtocol=https;AccountName=acct;"
        "AccountKey=synthetic-azure-account-key;EndpointSuffix=core\n",
        encoding="utf-8",
    )
    (root / "config" / "numeric.json").write_text(
        '{"prod2ApiKey": "example-credential"}\n', encoding="utf-8"
    )
    (root / "config" / "access-key.txt").write_text(
        'accessKey = "example-credential-value"\n', encoding="utf-8"
    )
    (root / "config" / "passphrase.json").write_text(
        '{"passphrase": "a-private-value"}\n', encoding="utf-8"
    )
    (root / "config" / "ordinary.json").write_text(
        '{"author": "alice", "keyboard": "qwerty", "compass": "north"}\n',
        encoding="utf-8",
    )
    (root / ".terraform").mkdir()
    (root / ".terraform" / "terraform.tfstate").write_text(
        '{"sensitive": true, "value": "synthetic-tf-password"}\n',
        encoding="utf-8",
    )
    (root / ".azure").mkdir()
    (root / ".azure" / "accessTokens.json").write_text(
        '{"accessToken": "synthetic-azure-token"}\n', encoding="utf-8"
    )
    (root / "application_default_credentials.json").write_text(
        '{"client_secret": "synthetic-gcloud-secret"}\n', encoding="utf-8"
    )
    (root / ".envrc").write_text(
        "export SERVICE_CRED=opaquevalue\n", encoding="utf-8"
    )
    (root / ".pgpass").write_text(
        "localhost:5432:app:alice:synthetic-pg-password\n", encoding="utf-8"
    )
    (root / ".htpasswd").write_text(
        "alice:$apr1$synthetic$hashvalue\n", encoding="utf-8"
    )
    (root / "config" / "google.json").write_text(
        '{"key": "AIzaExampleGoogleApiKey1234567890"}\n', encoding="utf-8"
    )
    (root / "config" / "slack-session.txt").write_text(
        "xoxc-example-slack-session-token\n", encoding="utf-8"
    )
    (root / "config" / "slack.json").write_text(
        '{"slack": "xoxb-example-slack-token"}\n', encoding="utf-8"
    )
    (root / "config" / "escaped.json").write_text(
        '{"pass\\u0077ord": "escaped-secret-value"}\n', encoding="utf-8"
    )
    (root / "config" / "auth.json").write_text(
        '{"auth": "sk-example-project-credential"}\n', encoding="utf-8"
    )
    (root / "config" / "credential.json").write_text(
        '{"credential": "sensitive-value"}\n', encoding="utf-8"
    )
    (root / "config" / "settings.xml").write_text(
        "<config><password>synthetic-xml-password</password>"
        '<property name="password" value="synthetic-xml-attribute"/>'
        "</config>\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged.yaml").write_text(
        "api_key: !vault |\n  synthetic-tagged-secret\n"
        "password: !!str |\n  synthetic-multibang-secret\n"
        "authorization: |\n  synthetic-authorization-token\n"
        "password: !!str\n  synthetic-tagged-plain\n"
        "password: &pw |\n  synthetic-anchored-secret\n"
        "password: plain-first\n  synthetic-plain-second\n"
        "password: &apw anchored-first\n  synthetic-anchored-plain\n"
        "password: &bare\n  synthetic-anchored-only\n"
        "password: !!str &saved\n  synthetic-tag-anchor\n"
        "pass: |\n  synthetic-pass-literal\n"
        "pass: >\n  synthetic-pass-folded\n",
        encoding="utf-8",
    )
    (root / "config" / "multiline.toml").write_text(
        'password = """\nsynthetic-multiline-secret\n"""\n',
        encoding="utf-8",
    )
    (root / "config" / "camel-credentials.txt").write_text(
        'openaiApiKey = "secret-value"\ngithubToken: ghp_example\n',
        encoding="utf-8",
    )
    (root / "config" / "camel.json").write_text(
        '{"dbPassword": "hunter2"}\n', encoding="utf-8"
    )
    (root / "config" / "structured.json").write_text(
        '{"api_key": ["first-secret", "second-secret"], '
        '"nested": {"api_key": "nested-secret"}, '
        '"password": {"nested": {"value": "nested-first"}, '
        '"backup": "nested-second"}}\n',
        encoding="utf-8",
    )
    (root / "config" / "settings.json").write_text(
        '{"api_key": "sk-json-secret-value", "region": "eu-central"}\n',
        encoding="utf-8",
    )
    (root / "config" / "database.py").write_text(
        'DATABASE_URL = "postgresql://alice:synthetic-password@db/app"\n'
        'DB_PASS = "synthetic-db-pass"\n'
        'APP_DB_PASS = "synthetic-app-db-pass"\n'
        'DB_PWD = "synthetic-db-pwd"\n',
        encoding="utf-8",
    )
    (root / "config" / "application.yaml").write_text(
        'api_key: |\n  sk-yaml-project-secret\n'
        '"quoted_key": |\n  sk-quoted-yaml-secret\n'
        "tokens:\n  - secret_key: |\n      sk-sequence-yaml-secret\n"
        "DB_PASS: |\n  synthetic-yaml-db-pass\n"
        "DB_PWD: >\n  synthetic-yaml-db-pwd\n"
        "blank_secret: |\n  first-part\n\n  second-part\n"
        "password: | # deployment credential\n  synthetic-comment-secret\n",
        encoding="utf-8",
    )
    (root / "binary.dat").write_bytes(b"\x00\x01secret-binary\x02")
    (root / ".git" / "config").write_text("url = https://example.invalid\n", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside-secret.txt").write_text("outside secret", encoding="utf-8")
    os.symlink(outside / "outside-secret.txt", root / "escape.txt")
    os.symlink(outside / "outside-secret.txt", root / "docs" / "leak.txt")
    return root


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "evalith.db",
        secret_key="test-secret-key",
        static_dir=tmp_path / "no-static",
        max_files=400,
        context_budget_chars=24_000,
        allow_paid_models=True,
    )


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def create_stub_model(client: TestClient, name: str = "stub") -> dict[str, Any]:
    response = client.post(
        "/api/model-configs",
        json={"name": name, "provider": "stub", "model_name": "stub-understanding"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def import_project(
    client: TestClient,
    root: Path,
    *,
    model_config_id: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    supplemental: list[dict[str, str]] | None = None,
    name: str = "Approval Agent",
) -> dict[str, Any]:
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "root_path": str(root),
            "model_config_id": model_config_id,
            "include_paths": include,
            "exclude_patterns": exclude,
            "supplemental": supplemental,
        },
    )
    return response


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    fail = False
    fail_body: str | None = None
    body_override: dict[str, Any] | None = None

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": raw.decode("utf-8", errors="replace"),
            }
        )
        if type(self).fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write((type(self).fail_body or "upstream failure").encode())
            return
        body = type(self).body_override or {
            "summary": "这是一个发布审批流程的初步理解。",
            "agent_or_flow": "release approval agent",
            "known": [
                {"text": "只有 release manager 可以发布。", "source": "docs/RELEASE_POLICY.md"}
            ],
            "inferred": [{"text": "存在发布门禁。", "basis": "政策文档标题"}],
            "unknowns": [{"text": "验收标准未知。", "why": "资料未写明"}],
            "sufficient": False,
            "sufficient_reason": "仍需确认验收标准。",
        }
        encoded = json.dumps(
            {"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: Any) -> None:
        return


@pytest.fixture()
def recording_server() -> Iterator[ThreadingHTTPServer]:
    _RecordingHandler.requests = []
    _RecordingHandler.fail = False
    _RecordingHandler.fail_body = None
    _RecordingHandler.body_override = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def outside_file(tmp_path: Path) -> Path:
    return tmp_path / "outside" / "outside-secret.txt"
