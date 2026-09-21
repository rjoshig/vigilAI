#!/usr/bin/env python3
"""Generate the synthetic fixture set for the test suite and the golden set.

Fixtures are synthetic only (ADR-003): every customer, state, threshold, and sample row
here is invented. A real customer file, or anything derived from one, never enters the
repo. The generator is seeded, so the same spec always produces byte-identical files and
tests can assert exact values.

Each *case* is a small spec describing one scenario: the OSL requirements, the config
that may or may not implement them, and the report numbers that may or may not agree.
The known-correct answer travels with the case, which is what makes the golden set
possible (milestone 2f).

Usage:
    python scripts/generate_fixtures.py --out tests/fixtures
    python scripts/generate_fixtures.py --out tests/fixtures --case baseline_match
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping, Sequence

_LOG: Final = logging.getLogger("generate_fixtures")

#: Invented customers. Deliberately unlike any real credit-bureau client name.
CUSTOMERS: Final[tuple[str, ...]] = (
    "Acme Card Services",
    "Northwind Lending",
    "Harbor Credit Union",
    "Pinecrest Auto Finance",
)

#: Invented attribute names, close enough in shape to a real layout to exercise the
#: alias logic without copying one.
ATTRIBUTES: Final[tuple[str, ...]] = (
    "SCORE_V3",
    "AGE",
    "ST",
    "REV_UTIL",
    "OPEN_TRADES",
    "INQ_6M",
    "TOT_BAL",
    "DELQ_30",
    "MORT_BAL",
    "BK_24M",
    "INCOME_EST",
    "DOB_YEAR",
    "SSN_LAST4",
    "FIRST_NAME",
)


@dataclass(frozen=True, slots=True)
class Criterion:
    """One numeric criterion shared by the OSL and (possibly) the config.

    Attributes:
        field_name: The attribute the criterion constrains, e.g. ``"SCORE_V3"``.
        label: How the OSL refers to it in prose, e.g. ``"score"``.
        operator: One of ``>=``, ``>``, ``<=``, ``<``.
        osl_value: The threshold the OSL states.
        config_value: The threshold the config uses. Differs from ``osl_value`` in a
            mismatch case; ``None`` means the config omits the rule entirely.
        delivered_min: The minimum the DIRT reports for this attribute.
        delivered_max: The maximum the DIRT reports.
        config_operator: The operator the config uses. ``None`` means it matches the
            OSL; setting it creates an operator mismatch with identical thresholds.
    """

    field_name: str
    label: str
    operator: str
    osl_value: float
    config_value: float | None
    delivered_min: float
    delivered_max: float
    config_operator: str | None = None


@dataclass(frozen=True, slots=True)
class Case:
    """One fixture scenario.

    Attributes:
        name: Directory name and identifier.
        description: What the scenario exercises, written into the manifest.
        customer: Which invented customer the run is for.
        order_number: Invented order number.
        configuration_id: Invented configuration id.
        osl_states: States the OSL allows.
        config_states: States the config filters on.
        report_states: States that appear in the state-distribution report.
        criteria: Numeric criteria.
        osl_attributes: Attributes the OSL asks for.
        config_attributes: Attributes the config outputs.
        report_attributes: Attributes the reports actually carry.
        waterfall: Step names in order, as the OSL states them.
        config_waterfall: Step names the config runs. ``None`` means it matches.
        extra_config_filter: An ``(attribute, threshold)`` the config filters on and the
            OSL never mentions, for the reverse pass.
        input_count: Records entering the flow.
        step_removals: Records removed at each step, parallel to ``waterfall`` after the
            first (input) step.
        unexplained_loss: Records that vanish with no step accounting for them. Non-zero
            makes the waterfall fail to reconcile.
        expected_findings: The known-correct answer: finding types this case must
            produce, used as the oracle by the golden set.
    """

    name: str
    description: str
    customer: str
    order_number: str
    configuration_id: str
    osl_states: tuple[str, ...]
    config_states: tuple[str, ...]
    report_states: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    osl_attributes: tuple[str, ...]
    config_attributes: tuple[str, ...]
    report_attributes: tuple[str, ...]
    waterfall: tuple[str, ...]
    config_waterfall: tuple[str, ...] | None = None
    extra_config_filter: tuple[str, float] | None = None
    input_count: int = 1_000_000
    step_removals: tuple[int, ...] = ()
    unexplained_loss: int = 0
    expected_findings: tuple[str, ...] = ()
    notes: str = ""
    #: The delivery programme this case belongs to, so the benchmark can report per
    #: programme (Phase 6.11b). Empty means unscoped, which most cases are.
    programme: str = ""
    #: Free-text clauses added to the OSL that no check can express. They extract as
    #: ``other`` requirements and so land in coverage as "verified by hand": the case
    #: for a requirement nothing in the reports evidences.
    free_text_requirements: tuple[str, ...] = ()
    #: An extra workbook of a kind no check covers, written and uploaded like any
    #: other. It should appear in coverage with zero checks applied.
    unchecked_report_kind: str = ""
    #: A credit date that appears in the OSL and in no report, which is a
    #: low-severity finding. No fixture produced one before, so nothing exercised the
    #: low-severity path (found in 6.11a).
    credit_date: str = ""
    #: How many requirements the run should leave unevidenced, as the oracle.
    expected_unevidenced: int = 0
    #: What this delivery calls each sheet, column and row label the fixed checks look
    #: for (Phase 6.21a). Empty means the names the checks ship with. A case that fills
    #: it ships a report whose layout drifted, which is what a real delivery does and
    #: what every fixture before 6.21 quietly assumed never happens.
    layout: Mapping[str, str] = field(default_factory=dict)
    #: What the DIRT calls each attribute, where that differs from the name the OSL
    #: uses (Phase 6.22a). Every case before this one spelled an attribute identically
    #: in the OSL and the DIRT, so nothing exercised the case a real delivery is full
    #: of: the OSL names a bureau attribute ``AT01`` and the delivered column is
    #: ``debsc_burs_atyrt_at01_1``. `layout` renames the *structure*; this renames the
    #: attribute itself, which is a different defect and was never covered.
    attribute_spellings: Mapping[str, str] = field(default_factory=dict)
    #: Whether this case ships a record layout — the delivered file's schema, one row
    #: per field with its name, data type and size (Phase 6.22b). Optional by design,
    #: so most cases carry none and exercise the path a delivery without one takes.
    record_layout: bool = False
    #: What the layout workbook heads its three columns, where that differs from what
    #: the parser asks for. A layout heading them ``Column Name``, ``Type`` and
    #: ``Length`` is the same document, and a parser that insists on one spelling is
    #: the shape defect 6.21a exists to stop.
    record_layout_headers: tuple[str, str, str] = ("Field name", "Data type", "Size")
    #: Fields the layout declares that the OSL never asked for. A delivery carrying
    #: more than the order named is a low-severity note, never a failure (6.22c).
    record_layout_extra: tuple[str, ...] = ()
    #: Attributes the record layout declares that the DIRT never reports on
    #: (Phase 6.22e). The delivered file ships the field and nothing measured it,
    #: which is the one case the DIRT alone cannot show.
    record_layout_unmeasured: tuple[str, ...] = ()
    #: A product code the OSL names instead of listing the attributes (Phase 6.22c).
    #: The OSL then says "deliver all attributes from ABC" and the attributes
    #: themselves are looked up in the catalogue — by code, never by the model.
    product_code: str = ""
    #: Codes the OSL names that the catalogue is not expected to define, so the case
    #: exercises the answer that matters most: an undefined code must never expand to
    #: nothing and let the delivery pass.
    unknown_product_codes: tuple[str, ...] = ()

    def delivered(self, name: str) -> str:
        """What the DIRT calls one attribute.

        Args:
            name: The attribute as the OSL names it.

        Returns:
            The delivery's own spelling, or ``name`` unchanged.
        """
        return self.attribute_spellings.get(name, name)

    def called(self, name: str) -> str:
        """What this delivery calls ``name``.

        Args:
            name: The name the fixed checks look for.

        Returns:
            The delivery's own spelling, or ``name`` unchanged.
        """
        return self.layout.get(name, name)


def _baseline_criteria(score_config: float | None = 755.0) -> tuple[Criterion, ...]:
    """Build the criteria used by most cases.

    Args:
        score_config: What the config uses for the score threshold. ``755`` matches the
            OSL; ``750`` creates a value mismatch; ``None`` omits the rule.

    Returns:
        The criteria tuple.
    """
    delivered_score_min = 755.0 if score_config is None else score_config
    return (
        Criterion("SCORE_V3", "score", ">=", 755.0, score_config, delivered_score_min, 850.0),
        Criterion("AGE", "age", ">=", 21.0, 21.0, 21.0, 94.0),
        Criterion("REV_UTIL", "revolving utilization", "<", 0.60, 0.60, 0.0, 0.599),
        Criterion("OPEN_TRADES", "open trades", ">=", 2.0, 2.0, 2.0, 41.0),
    )


#: The fixture set. Each case isolates one or two behaviours so a failing test names the
#: cause. ``expected_findings`` is the oracle.
CASES: Final[tuple[Case, ...]] = (
    Case(
        name="baseline_match",
        description="Config implements every OSL requirement; reports agree. No findings.",
        customer=CUSTOMERS[0],
        order_number="ORD-10001",
        configuration_id="CFG-SYNTH-BASELINE-01",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=(),
    ),
    Case(
        name="geography_extra_state",
        description=(
            "Config adds TX to the state filter and the report shows TX and NV. "
            "The design doc's worked example."
        ),
        customer=CUSTOMERS[0],
        order_number="ORD-10002",
        configuration_id="CFG-SYNTH-GEO-02",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ", "TX"),
        report_states=("IL", "AZ", "TX", "NV"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(500_000, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("extra_rule_in_config", "report_violates_rule"),
    ),
    Case(
        name="score_value_mismatch",
        description="Config threshold is 750 where the OSL says 755; DIRT confirms 750 delivered.",
        customer=CUSTOMERS[1],
        order_number="ORD-10003",
        configuration_id="CFG-SYNTH-SCORE-03",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(score_config=750.0),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 190_004, 3_905, 1_204, 2_109),
        expected_findings=("value_mismatch", "report_violates_rule"),
    ),
    Case(
        name="rule_missing_in_config",
        description="The OSL states a score rule the config does not implement at all.",
        customer=CUSTOMERS[2],
        order_number="ORD-10004",
        configuration_id="CFG-SYNTH-MISSING-04",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(score_config=None),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("rule_missing_in_config",),
    ),
    Case(
        name="attributes_missing_in_report",
        description="OSL and config ask for 11 attributes; the reports carry 10.",
        customer=CUSTOMERS[3],
        order_number="ORD-10005",
        configuration_id="CFG-SYNTH-ATTR-05",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:11],
        config_attributes=ATTRIBUTES[:11],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("report_violates_rule",),
    ),
    Case(
        name="attribute_renamed",
        description=(
            "A correct delivery whose DIRT spells every attribute the long way the "
            "source system does. Nothing is wrong with it."
        ),
        customer=CUSTOMERS[2],
        order_number="ORD-10011",
        configuration_id="CFG-SYNTH-RENAME-11",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        # Every attribute is delivered, under the name the source system gives it.
        # Before Phase 6.22a this produced one high-severity "the reports are missing
        # this attribute" per attribute, about a delivery that was entirely correct.
        attribute_spellings={
            name: f"debsc_burs_atyrt_{name.lower()}_1" for name in ATTRIBUTES[:10]
        },
        # It ships a record layout too (Phase 6.22b), spelled the delivered way like
        # the DIRT. That does not on its own resolve anything — the layout is a second
        # artifact to check against, not a mapping — but it is where the suggestion a
        # person accepts comes from (6.22f), and it makes this the realistic pairing:
        # a source system that respells everything documents the respelling.
        record_layout=True,
        expected_findings=("attribute_not_resolved",),
        # Five requirements stay unevidenced, and that is the correct answer: until the
        # dictionary of 6.22d exists, the tool genuinely cannot prove which DIRT column
        # is which attribute. It says so instead of guessing, and the coverage picture
        # shows the gap rather than hiding it behind a false pass.
        expected_unevidenced=5,
        notes=(
            "The case Phase 6.22a exists for: an unresolved attribute name is a "
            "review record, never a high-severity violation."
        ),
    ),
    Case(
        name="record_layout_supplied",
        description=(
            "A correct delivery that ships its record layout, headed the way a real "
            "layout workbook is headed rather than the way the parser asks. It also "
            "declares two fields the OSL never asked for."
        ),
        customer=CUSTOMERS[1],
        order_number="ORD-10018",
        configuration_id="CFG-SYNTH-LAYOUT-18",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:8],
        config_attributes=ATTRIBUTES[:8],
        report_attributes=ATTRIBUTES[:8],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        record_layout=True,
        # The three headings the parser asks for, written the way a source system
        # writes them. Nothing about this delivery is wrong; a parser that insisted on
        # one spelling would have reported a delivery with no declared fields at all.
        record_layout_headers=("Column Name", "Type", "Length"),
        # Two fields nobody asked for. A delivery carrying more than the order named
        # is a low-severity note and never a failure — and it is also a privacy
        # signal, because a field nobody asked for may be PII (Phase 6.22c).
        record_layout_extra=("INTERNAL_SEQ", "LOAD_TIMESTAMP"),
        expected_findings=(),
        notes=(
            "The record layout case: it parses through the ladder, it is promoted on "
            "finalize, and the next delivery of this configuration borrows it."
        ),
    ),
    Case(
        name="product_code_named",
        description=(
            "An OSL that names a product code instead of listing the attributes, plus "
            "one code the catalogue does not define. The delivery also carries two "
            "fields the code never listed."
        ),
        customer=CUSTOMERS[0],
        order_number="ORD-10019",
        configuration_id="CFG-SYNTH-PRODUCT-19",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:8],
        config_attributes=ATTRIBUTES[:8],
        report_attributes=ATTRIBUTES[:8],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        product_code="ABC",
        # A code nobody defined must never expand to nothing. "Check everything in
        # DEF" silently becoming "check nothing" would pass the delivery for the worst
        # possible reason: the tool could not say what was asked for.
        unknown_product_codes=("DEF",),
        record_layout=True,
        record_layout_extra=("INTERNAL_SEQ", "LOAD_TIMESTAMP"),
        expected_findings=("report_violates_rule",),
        notes=(
            "The product-code case. Seed ABC with this case's attributes and the "
            "fields_present check passes; leave DEF undefined and it is reported."
        ),
    ),
    Case(
        name="layout_declares_more_than_the_dirt",
        description=(
            "The record layout declares an attribute the OSL asks for and the DIRT "
            "never reports on. The delivered file ships the field and nothing "
            "measured it — the one case the DIRT alone cannot show."
        ),
        customer=CUSTOMERS[2],
        order_number="ORD-10020",
        configuration_id="CFG-SYNTH-UNMEASURED-20",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        # The OSL asks for nine; the reports carry eight. Before the record layout the
        # ninth was simply "missing", and it still would be without one.
        #
        # ``DOB_YEAR`` rather than the next name in the list, and deliberately.
        # ``MORT_BAL`` shares the word ``BAL`` with the delivered ``TOT_BAL``, so 6.22a
        # reads it as a near miss and answers "could not tell" — which is correct, and
        # is not the case this fixture is for. A name nothing in the DIRT resembles is
        # what makes the layout's answer the only one there is.
        osl_attributes=ATTRIBUTES[:8] + ("DOB_YEAR",),
        config_attributes=ATTRIBUTES[:8] + ("DOB_YEAR",),
        report_attributes=ATTRIBUTES[:8],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        record_layout=True,
        record_layout_unmeasured=("DOB_YEAR",),
        expected_findings=("report_violates_rule",),
        notes=(
            "Phase 6.22e: one alarm between the two artifacts, and the detail says "
            "which of them carried the attribute and which did not."
        ),
    ),
    Case(
        name="counts_do_not_reconcile",
        description="588 records vanish between exclusions and dedupe; accepts + rejects < input.",
        customer=CUSTOMERS[0],
        order_number="ORD-10006",
        configuration_id="CFG-SYNTH-COUNTS-06",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        unexplained_loss=588,
        expected_findings=("count_does_not_reconcile",),
    ),
    Case(
        name="operator_boundary_drift",
        description="Config uses > where the OSL says at least, so the boundary value differs.",
        customer=CUSTOMERS[1],
        order_number="ORD-10007",
        configuration_id="CFG-SYNTH-OPERATOR-07",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=(
            Criterion("SCORE_V3", "score", ">=", 755.0, 755.0, 755.0, 850.0, config_operator=">"),
            Criterion("AGE", "age", ">=", 21.0, 21.0, 21.0, 94.0),
            Criterion("REV_UTIL", "revolving utilization", "<", 0.60, 0.60, 0.0, 0.599),
            Criterion("OPEN_TRADES", "open trades", ">=", 2.0, 2.0, 2.0, 41.0),
        ),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("operator_mismatch",),
    ),
    Case(
        name="extra_config_filter",
        description="The config filters on an attribute the OSL never mentions.",
        customer=CUSTOMERS[2],
        order_number="ORD-10008",
        configuration_id="CFG-SYNTH-EXTRA-08",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=(
            Criterion("SCORE_V3", "score", ">=", 755.0, 755.0, 755.0, 850.0),
            Criterion("AGE", "age", ">=", 21.0, 21.0, 21.0, 94.0),
            Criterion("REV_UTIL", "revolving utilization", "<", 0.60, 0.60, 0.0, 0.599),
            Criterion("OPEN_TRADES", "open trades", ">=", 2.0, 2.0, 2.0, 41.0),
        ),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        extra_config_filter=("INCOME_EST", 40_000),
        expected_findings=("extra_rule_in_config",),
    ),
    Case(
        name="report_violates_state_rule",
        description="Config matches the OSL, but the delivered file contains an unlisted state.",
        customer=CUSTOMERS[3],
        order_number="ORD-10009",
        configuration_id="CFG-SYNTH-REPORTONLY-09",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ", "OH"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("report_violates_rule",),
    ),
    Case(
        name="missing_waterfall_step",
        description="The OSL requires an exclusions step the config pipeline does not run.",
        customer=CUSTOMERS[0],
        order_number="ORD-10010",
        configuration_id="CFG-SYNTH-STEPS-10",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        config_waterfall=("input", "geography", "score", "age", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("rule_missing_in_config",),
    ),
    Case(
        name="reordered_waterfall",
        description="The config runs the score step before geography; the OSL says otherwise.",
        customer=CUSTOMERS[1],
        order_number="ORD-10011",
        configuration_id="CFG-SYNTH-ORDER-11",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        config_waterfall=("input", "score", "geography", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=("waterfall_order_mismatch",),
    ),
    Case(
        name="missing_state_in_config",
        description="The OSL allows two states; the config filters to one of them.",
        customer=CUSTOMERS[2],
        order_number="ORD-10012",
        configuration_id="CFG-SYNTH-NARROW-12",
        osl_states=("IL", "AZ"),
        config_states=("IL",),
        report_states=("IL",),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(700_000, 150_000, 3_905, 1_204, 2_109),
        expected_findings=("rule_missing_in_config",),
    ),
    # --- the cases Phase 6.11 added ---------------------------------------------------
    Case(
        name="unevidenced_requirement",
        description=(
            "Everything the checks can compare agrees, and the OSL carries a clause "
            "no check can express. A clean findings list over an incomplete check."
        ),
        customer=CUSTOMERS[0],
        order_number="ORD-10020",
        configuration_id="CFG-SYNTH-UNEVIDENCED-20",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        programme="AS",
        free_text_requirements=(
            "Consumers who have opted out of firm offers of credit must be excluded "
            "from every delivery under this order.",
        ),
        expected_findings=(),
        expected_unevidenced=1,
        notes=(
            "The point of this case: the findings list is empty and the delivery has "
            "not been fully checked. Coverage is the only thing that says so."
        ),
    ),
    Case(
        name="report_nothing_checks",
        description=(
            "A report type the tool accepts and no check covers, delivered alongside "
            "the usual set."
        ),
        customer=CUSTOMERS[1],
        order_number="ORD-10021",
        configuration_id="CFG-SYNTH-UNCHECKED-REPORT-21",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        programme="AM",
        unchecked_report_kind="segment_summary",
        expected_findings=(),
        notes="Coverage should show segment_summary with no check applied.",
    ),
    Case(
        name="credit_date_not_in_reports",
        description=(
            "The credit date appears in the OSL and in no report, which is a "
            "low-severity finding. Before this, no fixture produced one at all."
        ),
        customer=CUSTOMERS[2],
        order_number="ORD-10022",
        configuration_id="CFG-SYNTH-CREDIT-DATE-22",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        credit_date="2026-07-15",
        expected_findings=("credit_date_missing",),
        notes="The low-severity path the bulk-OK test needed (found in 6.11a).",
    ),
    Case(
        name="layout_drift",
        description=(
            "Baseline again, delivered by a customer who names their sheets, headers "
            "and totals differently. Nothing is wrong with the delivery."
        ),
        customer=CUSTOMERS[1],
        order_number="ORD-10007",
        configuration_id="CFG-SYNTH-LAYOUT-07",
        osl_states=("IL", "AZ"),
        config_states=("IL", "AZ"),
        report_states=("IL", "AZ"),
        criteria=_baseline_criteria(),
        osl_attributes=ATTRIBUTES[:10],
        config_attributes=ATTRIBUTES[:10],
        report_attributes=ATTRIBUTES[:10],
        waterfall=("input", "geography", "score", "age", "exclusions", "dedupe"),
        input_count=1_000_000,
        step_removals=(612_440, 201_118, 3_905, 1_204, 2_109),
        expected_findings=(),
        layout={
            # Reached by the ladder's third rung: the same words, one or two more
            # besides. Before Phase 6.21 every one of these matched nothing.
            "Attributes": "Attribute Summary",
            "Attribute": "Attribute Name",
            "States": "State Breakdown",
            "State": "State Code",
            "Fields": "Field Values",
            "Field": "Field Name",
            "Flow": "Record Flow",
            "Input": "Input records",
            # Reached by no deterministic rung: "Accepts" and "Accepted" share no
            # token once the plural fold has run, which is the case the ladder's
            # fifth rung exists for. A run with no model leaves these two unresolved
            # and says so, which is the honest answer.
            "Accepts": "Accepted total",
            "Rejects": "Rejected total",
        },
        # One requirement stays unevidenced, and that is the oracle rather than a
        # defect: "Accepts" and "Accepted" share no token once the plural fold has
        # run, so the counts reconciliation needs the ladder's fifth rung. The golden
        # set runs on the mock, which answers "absent" by design, so this case scores
        # as a delivery whose counts nobody could check — which is exactly what a
        # deployment with no model configured would see.
        expected_unevidenced=1,
        notes=(
            "The Phase 6.21a case: a delivery that is entirely correct and whose "
            "layout is not what the checks ship with. Nine names resolve in code and "
            "two need the model."
        ),
    ),
)


# --------------------------------------------------------------------------------------
# OSL (.docx)
# --------------------------------------------------------------------------------------


def write_osl(case: Case, path: Path) -> None:
    """Write the synthetic OSL for a case.

    The wording deliberately varies between sections (prose in one place, a table in
    another, an equivalent-but-inverted phrasing for age) so stage 2 is exercised on more
    than one shape.

    Args:
        case: The scenario.
        path: Destination ``.docx`` path.
    """
    import docx

    document = docx.Document()
    document.add_heading(f"Order Specification Letter — {case.customer}", 0)

    document.add_heading("1 Purpose", level=1)
    document.add_paragraph(
        f"This specification governs order {case.order_number} for {case.customer}. "
        "All records delivered under this order must satisfy every requirement below."
    )

    document.add_heading("2 Population", level=1)
    document.add_paragraph(
        f"The input population is {case.input_count:,} consumer records drawn from the "
        "prescreen universe as of the pull date."
    )

    document.add_heading("3 Geography", level=1)
    states = " or ".join(_state_name(s) for s in case.osl_states)
    document.add_paragraph(
        f"Include only consumers whose current address is in {states}. "
        "No other states are in scope for this campaign."
    )

    document.add_heading("4 Credit criteria", level=1)
    document.add_paragraph(
        "Every accepted record must satisfy all of the criteria in the table below."
    )
    table = document.add_table(rows=1, cols=3)
    header = table.rows[0].cells
    header[0].text = "Attribute"
    header[1].text = "Condition"
    header[2].text = "Threshold"
    for criterion in case.criteria:
        row = table.add_row().cells
        row[0].text = criterion.label
        row[1].text = _condition_phrase(criterion.operator)
        row[2].text = _format_number(criterion.osl_value)

    document.add_heading("5 Output attributes", level=1)
    if case.product_code:
        # The OSL names a code rather than listing fields (Phase 6.22c). What the code
        # contains is looked up in the catalogue; the document does not say, which is
        # exactly the case the expansion exists for.
        named = ", ".join((case.product_code,) + case.unknown_product_codes)
        document.add_paragraph(
            f"Deliver all attributes from product code {named} for every accepted record."
        )
    else:
        document.add_paragraph(
            f"Deliver the following {len(case.osl_attributes)} attributes for every "
            "accepted record."
        )
        for index, attribute in enumerate(case.osl_attributes, start=1):
            document.add_paragraph(f"{index}. {attribute}", style="List Number")

    document.add_heading("6 Processing order", level=1)
    steps = ", then ".join(case.waterfall[1:])
    document.add_paragraph(
        f"Process in this order: {steps}. "
        "All input records must be accounted for as either accepted or rejected."
    )

    document.add_heading("7 Exclusions", level=1)
    document.add_paragraph("Exclude any consumer on the OFAC list.")
    document.add_paragraph("Exclude any consumer recorded as deceased.")

    if case.credit_date:
        document.add_heading("8 Credit date", level=1)
        document.add_paragraph(
            f"The delivery is cut as of {case.credit_date}. Every report must be "
            "produced from the same extract."
        )

    if case.free_text_requirements:
        document.add_heading("9 Additional requirements", level=1)
        for clause in case.free_text_requirements:
            document.add_paragraph(clause)

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))


def _state_name(code: str) -> str:
    """Expand a state code to its name, so the OSL reads like prose.

    Args:
        code: Two-letter state code.

    Returns:
        The state name, or the code when it is not in the small invented lookup.
    """
    names = {"IL": "Illinois", "AZ": "Arizona", "TX": "Texas", "NV": "Nevada", "OH": "Ohio"}
    return names.get(code, code)


def _condition_phrase(operator: str) -> str:
    """Render an operator the way a specification would word it.

    Args:
        operator: One of ``>=``, ``>``, ``<=``, ``<``.

    Returns:
        The prose phrasing, e.g. ``"at least"`` for ``>=``.
    """
    return {">=": "at least", ">": "greater than", "<=": "at most", "<": "below"}[operator]


def _format_number(value: float) -> str:
    """Format a threshold the way a specification would write it.

    Args:
        value: The threshold.

    Returns:
        An integer string when the value is whole, otherwise a percentage-style decimal.
    """
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


# --------------------------------------------------------------------------------------
# Config (.json)
# --------------------------------------------------------------------------------------


def _suppressions(case: Case) -> dict[str, object]:
    """The suppressions block, including one entry per free-text clause.

    A free-text clause the configuration implements is the case coverage exists for:
    it traces, nothing disagrees with it, and no report check can reach it, so the
    findings list is empty and part of the delivery was never compared. Leaving it
    unimplemented would instead make it an ordinary missing-rule finding, which is a
    different and already-covered case.

    Args:
        case: The scenario.

    Returns:
        The suppressions mapping.
    """
    block: dict[str, object] = {"ofac": True, "deceased": True}
    for index, clause in enumerate(case.free_text_requirements, start=1):
        block[f"policy_{index}"] = {"enabled": True, "describes": clause}
    return block


def write_config(case: Case, path: Path) -> None:
    """Write the synthetic ETL config for a case.

    Args:
        case: The scenario.
        path: Destination ``.json`` path.
    """
    filters: list[dict[str, object]] = [
        {"field": "ST", "op": "in", "value": list(case.config_states)},
    ]
    if case.extra_config_filter is not None:
        attribute, threshold = case.extra_config_filter
        filters.append({"field": attribute, "op": ">=", "value": threshold})

    rules: dict[str, object] = {}
    for criterion in case.criteria:
        if criterion.config_value is None:
            continue
        key = criterion.field_name.lower()
        operator = criterion.config_operator or criterion.operator
        bound = "max" if operator in ("<", "<=") else "min"
        rules[key] = {
            "field": criterion.field_name,
            "op": operator,
            bound: criterion.config_value,
        }

    document = {
        "configuration_id": case.configuration_id,
        "customer": case.customer,
        "last_modified": "2026-09-01T12:00:00Z",
        "source": {"table": "prescreen_universe", "driver": "synthetic"},
        "input": {"count": case.input_count},
        "filters": filters,
        "rules": rules,
        "suppressions": _suppressions(case),
        "dedupe": {"key": ["SSN", "ZIP"]},
        "output": {"fields": list(case.config_attributes)},
        "pipeline": {"steps": list(case.config_waterfall or case.waterfall)},
        "logging": {"level": "INFO", "destination": "stdout"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# Reports (.xlsx)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Flow:
    """Computed waterfall numbers for a case.

    Attributes:
        rows: ``(step, records_in, removed, records_out)`` per step.
        accepts: Final accepted count as the report states it.
        rejects: Rejected count as the report states it.
    """

    rows: tuple[tuple[str, int, int, int], ...]
    accepts: int
    rejects: int


def compute_flow(case: Case) -> _Flow:
    """Compute the waterfall the reports will state.

    ``unexplained_loss`` is subtracted after the last removal step without a step
    accounting for it, which is exactly the failure mode stage 7 must catch.

    Args:
        case: The scenario.

    Returns:
        The flow rows and the accept / reject totals.
    """
    rows: list[tuple[str, int, int, int]] = []
    remaining = case.input_count
    rows.append((case.waterfall[0], 0, 0, remaining))
    for step, removed in zip(case.waterfall[1:], case.step_removals):
        records_in = remaining
        remaining = records_in - removed
        rows.append((step, records_in, removed, remaining))
    accepts = remaining - case.unexplained_loss
    rejects = case.input_count - remaining
    return _Flow(rows=tuple(rows), accepts=accepts, rejects=rejects)


def write_reports(case: Case, directory: Path) -> dict[str, Path]:
    """Write every report workbook for a case.

    Args:
        case: The scenario.
        directory: Destination directory.

    Returns:
        A mapping of report kind to the file written.
    """
    import openpyxl

    directory.mkdir(parents=True, exist_ok=True)
    flow = compute_flow(case)
    written: dict[str, Path] = {}

    # --- DIRT -------------------------------------------------------------------------
    workbook = openpyxl.Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Label", "Value"])
    summary.append(["Customer", case.customer])
    summary.append(["Order number", case.order_number])
    summary.append(["Configuration id", case.configuration_id])
    summary.append(["Total rows", flow.accepts])
    summary.append(["Pull date", "2026-09-01"])

    attributes = workbook.create_sheet(case.called("Attributes"))
    attributes.append(
        [case.called("Attribute"), "Type", "Nulls", case.called("Min"), case.called("Max"), "Mean"]
    )
    by_field = {c.field_name: c for c in case.criteria}
    for name in case.report_attributes:
        # The delivered spelling, which for most cases is the OSL's own (Phase 6.22a).
        spelled = case.delivered(name)
        criterion = by_field.get(name)
        if criterion is not None:
            attributes.append(
                [
                    spelled,
                    "number",
                    0,
                    criterion.delivered_min,
                    criterion.delivered_max,
                    round((criterion.delivered_min + criterion.delivered_max) / 2, 2),
                ]
            )
        else:
            attributes.append([spelled, "number", 0, 0, 100, 50])

    sample = workbook.create_sheet("Sample")
    sample.append(["ROW", "ST", "SCORE_V3", "AGE", "SSN_LAST4", "FIRST_NAME"])
    for index, state in enumerate(case.report_states, start=1):
        sample.append([index, state, 780, 44, f"{1000 + index}", f"SYNTH{index}"])

    path = directory / "dirt.xlsx"
    workbook.save(path)
    written["dirt"] = path

    # --- State distribution -----------------------------------------------------------
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = case.called("States")
    sheet.append([case.called("State"), "Records"])
    share = max(flow.accepts // max(len(case.report_states), 1), 1)
    for state in case.report_states:
        sheet.append([state, share])
    path = directory / "state_distribution.xlsx"
    workbook.save(path)
    written["state_distribution"] = path

    # --- Field distribution -----------------------------------------------------------
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = case.called("Fields")
    sheet.append([case.called("Field"), "Distinct", "Nulls", "Null %"])
    for name in case.report_attributes:
        sheet.append([name, 120, 0, 0.0])
    path = directory / "field_distribution.xlsx"
    workbook.save(path)
    written["field_distribution"] = path

    # --- Counts / number flow ---------------------------------------------------------
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = case.called("Flow")
    sheet.append(["Step", "Records in", "Removed", "Records out"])
    for step, records_in, removed, records_out in flow.rows:
        sheet.append([step, records_in, removed, records_out])
    sheet.append([case.called("Accepts"), "", "", flow.accepts])
    sheet.append([case.called("Rejects"), "", "", flow.rejects])
    sheet.append([case.called("Input"), "", "", case.input_count])
    path = directory / "counts.xlsx"
    workbook.save(path)
    written["counts"] = path

    # --- Billing ----------------------------------------------------------------------
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Label", "Value"])
    sheet.append(["Billing count", flow.accepts])
    sheet.append(["Delivered count", flow.accepts])
    path = directory / "billing.xlsx"
    workbook.save(path)
    written["billing"] = path

    if case.unchecked_report_kind:
        # A workbook of a type the tool accepts and no check covers. It parses, it is
        # counted, and nothing asks it anything — which is exactly the silence
        # coverage exists to make loud (Phase 6.11c).
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Summary"
        sheet.append(["Label", "Value"])
        sheet.append(["Segment", "A"])
        sheet.append(["Records", flow.accepts])
        path = directory / f"{case.unchecked_report_kind}.xlsx"
        workbook.save(path)
        written[case.unchecked_report_kind] = path

    return written


def write_record_layout(case: Case, path: Path) -> None:
    """Write the case's record layout: the delivered file's schema (Phase 6.22b).

    Its field names are the **delivered** spellings, because a record layout describes
    the file that shipped — which is precisely what makes it able to answer "what does
    this DIRT call ``AT01``".

    Args:
        case: The scenario.
        path: Where to write the workbook.
    """
    import openpyxl

    path.parent.mkdir(parents=True, exist_ok=True)
    numeric = {c.field_name for c in case.criteria}
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Record layout"
    sheet.append(list(case.record_layout_headers))
    for name in case.report_attributes:
        sheet.append([case.delivered(name), "DECIMAL" if name in numeric else "CHAR", 10])
    for name in case.record_layout_unmeasured:
        sheet.append([name, "CHAR", 15])
    for name in case.record_layout_extra:
        sheet.append([name, "CHAR", 20])
    workbook.save(path)


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------


def generate(case: Case, root: Path) -> dict[str, object]:
    """Generate every file for one case and return its manifest entry.

    Args:
        case: The scenario.
        root: The fixtures root directory.

    Returns:
        The manifest entry describing what was written and what the oracle expects.
    """
    directory = root / "cases" / case.name
    osl_path = directory / "osl.docx"
    config_path = directory / "config.json"
    write_osl(case, osl_path)
    write_config(case, config_path)
    reports = write_reports(case, directory / "reports")
    layout_path: Path | None = None
    if case.record_layout:
        layout_path = directory / "record_layout.xlsx"
        write_record_layout(case, layout_path)
    flow = compute_flow(case)

    _LOG.info(
        "generated case %s (%d files)", case.name, 2 + len(reports) + (1 if layout_path else 0)
    )
    return {
        "name": case.name,
        "description": case.description,
        "customer": case.customer,
        "order_number": case.order_number,
        "configuration_id": case.configuration_id,
        "osl": str(osl_path.relative_to(root)),
        "config": str(config_path.relative_to(root)),
        "reports": {kind: str(p.relative_to(root)) for kind, p in reports.items()},
        # Optional, and most cases carry none: a delivery without a record layout is
        # checked exactly as it was before the slot existed (Phase 6.22b).
        "record_layout": str(layout_path.relative_to(root)) if layout_path else "",
        "expected": {
            "osl_states": list(case.osl_states),
            "config_states": list(case.config_states),
            "report_states": list(case.report_states),
            "accepts": flow.accepts,
            "rejects": flow.rejects,
            "input_count": case.input_count,
            "reconciles": flow.accepts + flow.rejects == case.input_count,
            "findings": list(case.expected_findings),
            "unevidenced": case.expected_unevidenced,
        },
        "programme": case.programme,
        "credit_date": case.credit_date,
        # The product codes the OSL names, and what the catalogue must define for
        # them, so a test can seed the catalogue this case assumes (Phase 6.22c).
        "product_code": case.product_code,
        "unknown_product_codes": list(case.unknown_product_codes),
        "product_code_attributes": list(case.osl_attributes) if case.product_code else [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Generate the synthetic fixture set (ADR-003: synthetic only).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("tests/fixtures"),
        help="Fixtures root directory (default: tests/fixtures).",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        help="Generate only this case; repeatable. Default: every case.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    selected = CASES if not args.case else tuple(c for c in CASES if c.name in set(args.case))
    if not selected:
        _LOG.error("no case matched %s; known cases: %s", args.case, [c.name for c in CASES])
        return 2

    root: Path = args.out
    entries = [generate(case, root) for case in selected]
    manifest = root / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"cases": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    _LOG.info("wrote %s with %d cases", manifest, len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
