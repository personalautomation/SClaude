#!/usr/bin/env python3
#
# What a product's review workflow has to write for sclaude, kept in step in
# three places: the code that reads it (sclaude/lib/review/pr_context.py), the
# section of docs/setup.md that tells a product, and the reference workflow a
# product copies (sclaude/templates/claude-code-review.yml).
#
# A string reworded in the code alone leaves products writing the old one, and
# sclaude reading every red check as work again — silently, since nothing
# fails on GitHub. So every coupled string must appear verbatim in the doc and
# in the template, and the template must still be a workflow whose structured
# output carries what the report step reads.
#
# Run it with: python3 tests/review-contract.py
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
TEMPLATE = os.path.join(ROOT, "sclaude", "templates", "claude-code-review.yml")
SETUP = os.path.join(ROOT, "docs", "setup.md")
HEADING = "## What sclaude reads from your review workflow"

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


spec = importlib.util.spec_from_file_location("pr_context",
                                              os.path.join(LIB, "review", "pr_context.py"))
pr_context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_context)

template = open(TEMPLATE, encoding="utf-8").read()
setup = open(SETUP, encoding="utf-8").read()
check("doc-section-exists", HEADING in setup, True)
section = setup[setup.find(HEADING):]
section = section[:section.find("\n## ", 1)] if "\n## " in section[1:] else section

# The workflow writes these; sclaude matches them.
coupled = {
    "findings-check": pr_context.FINDINGS_CHECK,
    "unthreaded-title": pr_context.UNTHREADED_TITLE,
    "unfinished-title": pr_context.UNFINISHED_TITLE,
    "counted-title": "unresolved review finding",
    "reviewed-mark": '"reviewed"',
    "not-reviewed-mark": '"not-reviewed"',
    "resolver-prefix": pr_context.RESOLVER_PREFIX.strip(),
    "decline-prefix": pr_context.DECLINE_PREFIX,
    "no-review-label": "no-review",
    "review-comment": "/review",
    "minor-mark": pr_context.MINOR_MARK,
}
for name, text in coupled.items():
    check("template-carries-%s" % name, text in template, True)
    bare = text.strip('"')
    check("doc-carries-%s" % name, bare in section, True)

# Both minor marks the template has the review write are the ones
# pr_context reads back (minor_of), and the doc names both.
for kind in pr_context.MINOR_KINDS:
    line = pr_context.minor_mark(kind)
    check("template-writes-minor-%s" % kind, line in template, True)
    check("doc-names-minor-%s" % kind, line in section, True)
    check("minor-%s-read" % kind, pr_context.minor_of(line + "\n\n**finding**"), kind)

# The counted title is read by a pattern: the template's wording must match it.
check("counted-title-read", bool(re.search(r"(\d+) unresolved review finding",
                                           "3 unresolved review findings in the whole PR")), True)
check("template-counts-in-title", "unresolved review findings in the whole PR" in template, True)

# The unfinished title the template writes is the one review_unfinished reads.
title = re.search(r'elif \$incomplete then "([^"]+)"', template)
check("template-writes-unfinished-title", bool(title), True)
if title:
    check("unfinished-title-read", pr_context.review_unfinished({
        "status": "completed", "conclusion": "failure", "external_id": "not-reviewed",
        "output": {"title": title.group(1)}}), True)

# Findings posted as a comment keep their title over an unfinished review:
# they are a session's work, and review_unfinished refuses that title.
check("unthreaded-title-first", template.find('if $u > 0 then') < template.find('elif $incomplete then'), True)
check("unthreaded-not-unfinished", pr_context.review_unfinished({
    "status": "completed", "conclusion": "failure", "external_id": "not-reviewed",
    "output": {"title": "2 review findings %s; the %s" % (pr_context.UNTHREADED_TITLE,
                                                         pr_context.UNFINISHED_TITLE)}}), False)

# The structured output asks for `complete`, and the schema is valid JSON.
schema = re.search(r"--json-schema '(\{.*\})'", template)
check("template-has-schema", bool(schema), True)
if schema:
    try:
        parsed = json.loads(schema.group(1))
    except ValueError as exc:
        parsed = {}
        failures.append(("schema-is-json", "valid JSON", str(exc)))
    check("schema-requires-complete", "complete" in parsed.get("required", []), True)
    check("schema-complete-is-boolean",
          (parsed.get("properties", {}).get("complete") or {}).get("type"), "boolean")
    # What review_log.py reads of the run's answer from its job's log.
    for key in ("found", "resolved", "full_rerun", "complete"):
        check("schema-has-%s" % key, key in parsed.get("required", []), True)
        check("doc-names-%s" % key, "`%s`" % key in section, True)

# Where the run's delta began, which review_log.py reads from the file the
# workflow hands the review.
check("template-base-sha", "base_sha:" in template and ".claude-review/open-findings.json" in template, True)
check("doc-base-sha", "`base_sha`" in section and "open-findings.json" in section, True)

# The run's conversation in its job's log, which review_log.py reads.
check("template-full-output", "show_full_output: true" in template, True)
check("doc-full-output", "show_full_output:\ntrue" in section or "show_full_output: true" in section, True)

# It parses as YAML, when PyYAML is there to say so.
try:
    import yaml
except ImportError:
    yaml = None
if yaml is not None:
    try:
        doc = yaml.safe_load(template)
        check("template-is-a-workflow", isinstance(doc, dict) and "jobs" in doc, True)
    except yaml.YAMLError as exc:
        failures.append(("template-yaml", "parses", str(exc)))

# A product reads the template from the doc's link.
check("doc-names-template", "sclaude/templates/claude-code-review.yml" in section, True)

if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
