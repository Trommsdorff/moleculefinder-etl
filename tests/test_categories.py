"""Every functional-group SMARTS, pinned with molecules it must and must not match.

Each pattern becomes an /in/<slug> hub, which is a published claim about what a molecule's
structure contains. Until 2026-09-12 the carboxylic-acids pattern matched a carbonyl carbon
bonded only to oxygens, so bicarbonate and three of its salts were listed as carboxylic acids
(feedback triage MF-3). These cases are the regression net for every pattern in the table,
not only that one: a new group added to FUNCTIONAL_GROUPS fails here until it has cases.
"""
from __future__ import annotations

import pytest

from moleculefinder_etl.transform.categories import FUNCTIONAL_GROUPS, functional_groups

# slug -> ({name: SMILES that must match}, {name: SMILES that must not match})
CASES: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "alcohols": (
        {"ethanol": "CCO", "glycerol": "OCC(O)CO", "menthol": "CC(C)C1CCC(C)CC1O"},
        {"phenol": "Oc1ccccc1", "acetic acid": "CC(=O)O", "dimethyl ether": "COC",
         "acetone": "CC(C)=O"},
    ),
    "carboxylic-acids": (
        {"formic acid": "OC=O", "acetic acid": "CC(=O)O", "benzoic acid": "OC(=O)c1ccccc1",
         "ibuprofen": "CC(C)Cc1ccc(cc1)C(C)C(=O)O"},
        # The first four are the snapshot's own SMILES for the molecules that left the hub.
        {"bicarbonate": "C(=O)(O)[O-]", "sodium bicarbonate": "C(=O)(O)[O-].[Na+]",
         "potassium bicarbonate": "C(=O)(O)[O-].[K+]",
         "ammonium bicarbonate": "C(=O)(O)[O-].[NH4+]",
         "carbonic acid": "OC(=O)O", "carbamic acid": "NC(=O)O", "urea": "NC(N)=O",
         "methocarbamol": "COc1ccccc1OCC(O)COC(N)=O"},
    ),
    "amines": (
        {"methylamine": "CN", "dopamine": "NCCc1ccc(O)c(O)c1", "amphetamine": "CC(N)Cc1ccccc1"},
        {"trimethylamine": "CN(C)C", "acetamide": "CC(N)=O", "urea": "NC(N)=O",
         "caffeine": "Cn1cnc2c1c(=O)n(C)c(=O)n2C"},
    ),
    "aromatics": (
        {"benzene": "c1ccccc1", "toluene": "Cc1ccccc1", "aspirin": "CC(=O)Oc1ccccc1C(=O)O"},
        {"cyclohexane": "C1CCCCC1", "pyridine": "c1ccncc1", "ethanol": "CCO"},
    ),
    "ketones": (
        {"acetone": "CC(C)=O", "raspberry ketone": "CC(=O)CCc1ccc(O)cc1",
         "camphor": "CC1(C)C2CCC1(C)C(=O)C2"},
        {"acetaldehyde": "CC=O", "acetic acid": "CC(=O)O", "ethyl acetate": "CCOC(C)=O",
         "acetamide": "CC(N)=O"},
    ),
    "aldehydes": (
        {"formaldehyde": "C=O", "acetaldehyde": "CC=O", "vanillin": "COc1cc(C=O)ccc1O"},
        {"acetone": "CC(C)=O", "acetic acid": "CC(=O)O", "benzoic acid": "OC(=O)c1ccccc1",
         "ethyl acetate": "CCOC(C)=O"},
    ),
    "esters": (
        {"ethyl acetate": "CCOC(C)=O", "methyl salicylate": "COC(=O)c1ccccc1O",
         "aspirin": "CC(=O)Oc1ccccc1C(=O)O"},
        {"acetic acid": "CC(=O)O", "diethyl ether": "CCOCC", "acetone": "CC(C)=O",
         "acetamide": "CC(N)=O"},
    ),
    "amides": (
        {"acetamide": "CC(N)=O", "acetaminophen": "CC(=O)Nc1ccc(O)cc1",
         "capsaicin": "COc1cc(CNC(=O)CCCC/C=C/C(C)C)ccc1O"},
        {"urea": "NC(N)=O", "carbamic acid": "NC(=O)O", "methylamine": "CN",
         "acetic acid": "CC(=O)O"},
    ),
    "phenols": (
        {"phenol": "Oc1ccccc1", "acetaminophen": "CC(=O)Nc1ccc(O)cc1",
         "vanillin": "COc1cc(C=O)ccc1O"},
        {"benzyl alcohol": "OCc1ccccc1", "anisole": "COc1ccccc1",
         "benzoic acid": "OC(=O)c1ccccc1"},
    ),
    "thiols": (
        {"methanethiol": "CS", "ethanethiol": "CCS", "cysteine": "NC(CS)C(=O)O"},
        {"dimethyl sulfide": "CSC", "methionine": "CSCCC(N)C(=O)O",
         "taurine": "NCCS(=O)(=O)O"},
    ),
    "ethers": (
        {"diethyl ether": "CCOCC", "anisole": "COc1ccccc1", "tetrahydrofuran": "C1CCOC1"},
        {"ethyl acetate": "CCOC(C)=O", "ethanol": "CCO", "acetic acid": "CC(=O)O", "water": "O"},
    ),
    "halogenated": (
        {"chloroform": "ClC(Cl)Cl", "iodoform": "IC(I)I",
         "fluoxetine": "CNCCC(Oc1ccc(cc1)C(F)(F)F)c1ccccc1"},
        {"ethanol": "CCO", "benzene": "c1ccccc1", "glucose": "OCC1OC(O)C(O)C(O)C1O"},
    ),
    "phosphates": (
        {"phosphoric acid": "OP(=O)(O)O", "dimethyl phosphate": "COP(=O)(O)OC",
         "dihydrogen phosphate": "OP(=O)(O)[O-]"},
        {"triphenylphosphine": "c1ccc(cc1)P(c1ccccc1)c1ccccc1", "sulfuric acid": "OS(=O)(=O)O",
         "ethanol": "CCO"},
    ),
}

POSITIVE = [(slug, name, smi) for slug, (pos, _) in CASES.items() for name, smi in pos.items()]
NEGATIVE = [(slug, name, smi) for slug, (_, neg) in CASES.items() for name, smi in neg.items()]


def test_every_group_in_the_table_has_cases_and_no_case_names_an_unknown_group():
    assert set(CASES) == set(FUNCTIONAL_GROUPS)


@pytest.mark.parametrize("slug", sorted(FUNCTIONAL_GROUPS))
def test_at_least_two_positives_and_two_negatives(slug):
    positives, negatives = CASES[slug]
    assert len(positives) >= 2 and len(negatives) >= 2


@pytest.mark.parametrize("slug,name,smiles", POSITIVE, ids=[f"{s}+{n}" for s, n, _ in POSITIVE])
def test_the_group_matches(slug, name, smiles):
    assert slug in functional_groups(smiles), f"{name} ({smiles}) should be in {slug}"


@pytest.mark.parametrize("slug,name,smiles", NEGATIVE, ids=[f"{s}-{n}" for s, n, _ in NEGATIVE])
def test_the_group_does_not_match(slug, name, smiles):
    assert slug not in functional_groups(smiles), f"{name} ({smiles}) must not be in {slug}"


def test_the_replaced_pattern_really_did_let_these_in():
    """A guard on the reasoning: the old carboxylic-acids SMARTS matched the carbonates and the
    carbamate, so the negative cases above are load-bearing and not vacuously true."""
    from rdkit import Chem
    old = Chem.MolFromSmarts("[CX3](=O)[OX2H1]")
    for smiles in ("C(=O)(O)[O-].[Na+]", "C(=O)(O)[O-]", "OC(=O)O", "NC(=O)O"):
        assert Chem.MolFromSmiles(smiles).HasSubstructMatch(old)


def test_no_structure_is_no_groups():
    assert functional_groups("") == []
    assert functional_groups("not a smiles") == []
