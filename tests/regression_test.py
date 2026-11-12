"""
RAG Regression Test Pipeline — Kuldeep Chatbot
===============================================
Runs a curated set of predefined questions through the live Flask backend,
collects each answer and its retrieved context chunks, evaluates them with
Ragas, and **fails (exit code 1) if any metric drops below its threshold**.

Four Ragas metrics are measured:

  faithfulness        – answer stays grounded in retrieved context        (default threshold: 0.70)
  answer_relevancy    – answer addresses the question asked               (default threshold: 0.70)
  context_precision   – retrieved chunks are relevant to the question     (default threshold: 0.60)
  context_recall      – context covers the key facts in the ground truth  (default threshold: 0.60)

Usage
-----
  # Run from the project root with the Flask backend already running:
  # Set REGRESSION_USERNAME and REGRESSION_PASSWORD to an existing test account.
  python tests/regression_test.py

  # Informational run — report scores but do NOT fail on threshold violations:
  python tests/regression_test.py --no-fail

  # Override thresholds on the command line:
  python tests/regression_test.py --faithfulness 0.75 --answer-relevancy 0.80

Requirements
------------
  pip install ragas
  Flask backend running on http://localhost:5000

Adding or customising test cases
---------------------------------
Edit the REGRESSION_TESTS list below.  Each entry is a dict with:

  id           (str)  – unique identifier shown in the report
  category     (str)  – logical grouping label
  question     (str)  – the question sent to the chatbot
  ground_truth (str)  – the "ideal" answer text used for context_precision
                        and context_recall scoring.  Keep it factual and
                        specific; vague ground truths produce noisy scores.

Ground truth guidelines
-----------------------
  • Write in plain prose, not bullet points.
  • Include the key fact(s) you expect the RAG system to retrieve.
  • Keep it short (1–3 sentences).  Ragas uses it to judge what the
    *context* should contain, not to grade the exact wording of the answer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Optional

import requests

# ── Backend endpoints ─────────────────────────────────────────────────────────

CHAT_URL  = "http://localhost:5000/chat"
SESSION_URL = "http://localhost:5000/users/session"
LOGIN_URL = "http://localhost:5000/users/login"
CLEAR_URL = "http://localhost:5000/api/clear"
RESULTS_DIR = os.path.join(os.path.dirname(__file__))
API_SESSION = requests.Session()
TAB_ID = str(uuid.uuid4())

# ── Score thresholds (override via CLI args) ──────────────────────────────────

DEFAULT_THRESHOLDS: dict[str, float] = {
    "faithfulness":      0.70,
    "answer_relevancy":  0.70,
    "context_precision": 0.60,
    "context_recall":    0.60,
}

# ── Regression test cases ─────────────────────────────────────────────────────
# ground_truth is used only for context_precision and context_recall.
# All ground truths are copied directly from source documents (not AI-generated).

REGRESSION_TESTS: list[dict] = [

    # ── FDA Food Code ─────────────────────────────────────────────────────────
    {
        "id": "REG-01",
        "category": "food-safety",
        "question": "According to the FDA Food Code 2019, what hand drying provisions are required for food employees?",
        "ground_truth": (
            "The FDA Food Code requires provisions for hand drying so that employees will not "
            "dry their hands on their clothing or other unclean materials. "
            "Wet hands transfer bacteria more readily than dry hands, and the method of drying "
            "is a critical factor in reducing cross-contamination. "
            "Air knife technology has been found to be equivalent to existing heated-air hand "
            "drying devices, but may not accommodate drying of forearms or prosthetic devices, "
            "requiring an alternate drying means in those cases."
        ),
    },
    {
        "id": "REG-02",
        "category": "food-safety",
        "question": "According to the FDA Food Code 2019, what handwashing signage is required at food establishments?",
        "ground_truth": (
            "The FDA Food Code requires a sign or poster to be posted at handwashing sinks "
            "to remind food employees to wash their hands."
        ),
    },

    # ── Manufacturing Processes ───────────────────────────────────────────────
    {
        "id": "REG-03",
        "category": "manufacturing",
        "question": "In the Manufacturing Processes document, what are the three distinct zones of a fatigue fracture?",
        "ground_truth": (
            "The three distinct zones of a fatigue fracture are the point of crack initiation, "
            "the area of crack propagation during service, and the remaining area of "
            "cross-section showing signs of sudden breakage."
        ),
    },
    {
        "id": "REG-04",
        "category": "manufacturing",
        "question": "According to the Manufacturing Processes document, what is creep failure?",
        "ground_truth": (
            "Creep failure occurs when materials deform plastically at a very slow rate under "
            "steady loads, especially at high temperatures, leading to ultimate failure over time. "
            "This type of failure is common in components like stays in boilers and turbine blades."
        ),
    },
    {
        "id": "REG-05",
        "category": "manufacturing",
        "question": "According to the Manufacturing Processes document, what are some benefits of using alloy steel?",
        "ground_truth": (
            "Alloying in steels can lead to hardening by heat treatment, corrosion resistance, "
            "red hardness in cutting tools, increased strength and toughness, resistance to "
            "grain growth, and oxidation at high temperatures. "
            "The main alloying elements used in alloy steels are chromium, nickel, tungsten, "
            "molybdenum, vanadium, cobalt, manganese, and silicon. "
            "Alloy steels are available in various types, categorized into stainless steels, "
            "tool steel, and special steels. "
            "Nickel, chromium, and silicon are specific alloying elements used in nickel steels, "
            "chromium steels, and silicon steels respectively. "
            "Alloying elements can significantly improve the properties of cast iron and plain "
            "carbon steels. "
            "Alloy cast irons have higher strength, heat-resistance, and wear-resistance "
            "compared to plain cast iron."
        ),
    },
    {
        "id": "REG-06",
        "category": "manufacturing",
        "question": "According to the Manufacturing Processes document, what are the steps for heat treatment?",
        "ground_truth": (
            "Heat treatment of carbon steels involves three basic steps: heating the metal to a "
            "specific temperature, soaking it at that temperature for uniformity, and cooling it "
            "at a controlled rate in water, oil, or air. "
            "Carbon steels undergo four basic heat-treatment processes: annealing, normalizing, "
            "hardening, and tempering. "
            "Annealing softens the material and removes internal stresses based on the carbon "
            "content of the steel. "
            "Normalizing involves heating, soaking, and cooling the steel in still air to "
            "eliminate internal stresses and refine the grain structure. "
            "Hardening includes heating, soaking, and quenching the steel in water or oil to "
            "increase hardness, followed by tempering to reduce brittleness. "
            "Case hardening is used for low carbon steels by packing the workpiece in charcoal "
            "to introduce carbon into the surface."
        ),
    },

    # ── Machine Tool Operations ───────────────────────────────────────────────
    {
        "id": "REG-07",
        "category": "machining",
        "question": "According to the Basic Machine Tool Operations Aug 2017 document, what are the Machine Shop Rules?",
        "ground_truth": (
            "Students are not permitted to work without a Supervisor in the Machine Shop. "
            "Students must scan their I.D. card upon entering and display their printed label "
            "in a visible location. "
            "When working in the shop, two people must be present at all times. "
            "Buddy's are not to touch machinery controls. "
            "Safety glasses must be worn at all times; tinted or sunglasses are not permitted. "
            "No sandals or open-toe shoes are allowed; work boots or street shoes only. "
            "Do not wear loose clothing or jewelry; tie back long hair. "
            "Safety Data Sheets must be supplied on materials not listed in shop SDS book before "
            "work can begin. "
            "Dispose of waste according to the SDS sheets and posted signs. "
            "No part washing in the sinks; sinks are for hand washing only. "
            "Do not lay rags on lathe, mill or moving machinery. "
            "Do not enter the shop under the influence of drugs or alcohol. "
            "All metal scraps and cuttings are to be disposed of in the proper recycling drum. "
            "Only certified students are allowed to operate the equipment of which they are "
            "certified to use. "
            "Students should never talk on a cell phone while operating equipment. "
            "The Supervisor must check all machine setups before machine operation begins. "
            "No arguing or horseplay in the shop. "
            "No eating or drinking in the shop. "
            "Tools are not to be removed from building 538. "
            "Put tools back to where they belong. "
            "Clean off machines and/or tools after use."
        ),
    },
    {
        "id": "REG-08",
        "category": "machining",
        "question": "According to the Basic Machine Tool Operations Aug 2017 document, how do I clean a lathe?",
        "ground_truth": (
            "A lathe should be cleaned after each work period. "
            "Remove chips with a paint brush, not your hand, and wipe all painted surfaces "
            "with a soft cloth. "
            "Move the tailstock to the extreme right and wipe remaining oil, chips and dirt "
            "from machined surfaces; do not use compressed air as flying chips are dangerous. "
            "The lead screw can be cleaned by running the lathe at slow speed and feeding a "
            "piece of cord along the threads, but never wrap the cord around your hand."
        ),
    },
    {
        "id": "REG-09",
        "category": "machining",
        "question": "In the Basic Machine Tool Operations Aug 2017 document, what is Skip Lot sampling?",
        "ground_truth": (
            "Skip Lot sampling means that only a fraction of the submitted lots are inspected. "
            "This mode of sampling is of the cost-saving variety in terms of time and effort, "
            "but should only be used when it has been demonstrated that the quality of the "
            "submitted product is very good."
        ),
    },
    {
        "id": "REG-10",
        "category": "machining",
        "question": "In the Basic Machine Tool Operations Aug 2017 document, what does laying out mean and what tools are used? Explain in a simple way.",
        "ground_truth": (
            "Laying out is the term used to describe the locating and marking out of lines, "
            "circles, arcs and points for drilling holes. "
            "These lines and reference points on the metal show the machinist where to machine. "
            "The tools used for this work are known as layout tools."
        ),
    },

    # ── Boeing Lean Manufacturing ─────────────────────────────────────────────
    {
        "id": "REG-11",
        "category": "lean-manufacturing",
        "question": "In the Boeing Lean Manufacturing Studies, what is Value Stream?",
        "ground_truth": (
            "The Value Stream is the set of specific actions required to bring a specific "
            "product through three critical management tasks of any business: problem solving, "
            "information management, and physical transformation."
        ),
    },
    {
        "id": "REG-12",
        "category": "lean-manufacturing",
        "question": "In the Boeing Lean Manufacturing Studies, what resource productivity gains did Boeing achieve from the new shipping process?",
        "ground_truth": (
            "Multiple transfers, rail travel, and truck travel to the rail heads have been "
            "completely eliminated. "
            "Trucks no longer run empty from Kansas City to Tulsa because shipping by rail "
            "has been removed from the process. "
            "Eight days of travel and three days of receiving and inspection have been eliminated. "
            "Approximately $7,900 has been saved per shipset, or $396,000 in annual "
            "transportation costs. "
            "Floor grid inventory has been reduced by 25 percent. "
            "Each ship set uses 50 percent less transportation. "
            "Overall handling of materials has been reduced, yielding a reduction in forklift use. "
            "In response to Boeing's new shipping process, the floor grid component suppliers "
            "have adjusted their manufacturing schedules so that they do not produce and "
            "accumulate excess inventory at their production sites."
        ),
    },
    {
        "id": "REG-13",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, what does monuments mean and give me two examples?",
        "ground_truth": (
            "Monuments are production processes or process steps that have large equipment "
            "and/or other physical or environmental regulatory constraints, are very difficult "
            "or costly to move, and can disrupt the flow sought through Lean. "
            "Examples include painting processes with large fixed paint booths or dipping tanks, "
            "and metal finishing processes with large tanks and/or fixed equipment."
        ),
    },

    # ── Maintenance & Calibration SOP ─────────────────────────────────────────
    {
        "id": "REG-15",
        "category": "calibration",
        "question": "According to the SOP Maintenance and Calibration of Equipment, what is the difference between preventive maintenance and corrective maintenance?",
        "ground_truth": (
            "Preventive maintenance consists of maintenance activities carried out periodically "
            "according to criteria defined by the official equipment maintainer. "
            "Corrective maintenance consists of maintenance activities performed on equipment "
            "when an incident is detected in its normal operation."
        ),
    },

    # ── CNC / Autodesk ────────────────────────────────────────────────────────
    {
        "id": "REG-16",
        "category": "cnc",
        "question": "According to the Autodesk CNCbook, what are the required clothes for working in the CNC shop?",
        "ground_truth": (
            "ANSI approved safety glasses must be worn at all times in the shop, not just "
            "when at the machine. "
            "Do not wear flip flops or sandals; leather shoes are best. "
            "Do not wear long sleeve shirts as these could get caught in equipment; wear "
            "short sleeves or T-shirts. "
            "Remove rings and watches when at the machine. "
            "Do not wear short pants; wear sturdy long pants like blue jeans or work pants. "
            "Long hair should be tied back or under a hat to prevent it being caught in the "
            "machine spindle. "
            "Never wear gloves as they can be caught in the machine; latex gloves are acceptable."
        ),
    },
    {
        "id": "REG-17",
        "category": "cnc",
        "question": "According to the Autodesk CNCbook, what is the difference between a subplate and an angle plate?",
        "ground_truth": (
            "A subplate is a ground aluminum plate that bolts to the top of the machine table "
            "and has threaded holes and bushings at regular intervals. "
            "An angle plate is a precision ground steel plate that allows the part to be set "
            "on its side, and can point in a direction parallel to either the X or Y axis."
        ),
    },
    {
        "id": "REG-18",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, what are the varieties of milling cutter tool constructions?",
        "ground_truth": (
            "Solid cutters are made from a single piece of HSS or carbide; cutters can be "
            "tipped with a harder material; teeth can be designed for specific cutting "
            "conditions; low initial cost. "
            "Inserted blade cutters are usually made from HSS, carbide, or cast alloy; "
            "individual blades can be replaced as they wear out, saving replacement cost; "
            "ideal for close-tolerance finishing. "
            "Indexable insert cutters use inserts made from carbide, coated carbide, ceramic, "
            "or ultrahard material such as diamond; each insert has one or more cutting edges; "
            "as inserts wear they are repositioned to expose new cutting surface or indexed to "
            "bring another cutting insert on line."
        ),
    },

    # ── Server / Error Codes ──────────────────────────────────────────────────
    {
        "id": "REG-19",
        "category": "server",
        "question": "In the server installation guide error codes document, what is error code 8x1A?",
        "ground_truth": (
            "Error code 8x1A indicates an AC Voltage Surge. "
            "If the fault persists, check the AC connection to the inverter, verify the "
            "inverter is set to the correct country, check with the grid operator if a large "
            "surge source or irregular load exists near the site, and verify that the output "
            "wire size matches the distance between the inverter and the grid connection."
        ),
    },

    # ── Modern Manufacturing (Laser / Welding) ────────────────────────────────
    {
        "id": "REG-20",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, what are the general processing guidelines for laser surface hardening?",
        "ground_truth": (
            "The range of usable power densities for laser surface hardening is 3200 W/in² "
            "(500 W/cm²) to 32,000 W/in² (5000 W/cm²) with beam dwell times from 0.1 to "
            "10 seconds; higher power levels would melt the surface. "
            "Alloys with high hardenability can be processed at low speed with low power "
            "density to produce relatively thick cases. "
            "Alloys with low hardenability should be processed at high speed with high power "
            "density; the result is a shallow case. "
            "Beam configuration can be rectangular, square, or round, and uniform energy "
            "density within the beam is very important. "
            "Maximum achievable surface temperature is proportional to the square root of the "
            "processing speed; thus doubling the beam power density requires the processing "
            "speed to be increased by a factor of four to maintain the equivalent maximum "
            "surface temperature. "
            "Smaller workpieces are not as effective a heat sink as larger workpieces, and "
            "hence self-quenching may have to be assisted by quenching media."
        ),
    },
    {
        "id": "REG-21",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, what is laser surface hardening?",
        "ground_truth": (
            "Laser surface hardening is used as an alternative to flame hardening and "
            "induction hardening of ferrous materials. "
            "The rapid heating rate achievable by the laser minimizes part distortion and "
            "can impart surface hardness to low-carbon steels. "
            "This process is used to harden selected areas of machine components such as "
            "gears, cylinders, bearings, and shafts, and the entire operation can be "
            "performed in air."
        ),
    },
    {
        "id": "REG-22",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, explain the key system components for laser surface hardening.",
        "ground_truth": (
            "The majority of industrial metalworking lasers are either solid-state Nd:YAG "
            "or carbon dioxide type; power output for YAG lasers is 50 to 500 W and carbon "
            "dioxide lasers are available up to 25 kW. "
            "The surface to be hardened is usually coated to improve its ability to absorb "
            "laser radiation; a typical coating is manganese phosphate, and paints containing "
            "graphite, silicon, and carbon are also used, increasing absorption to 80 to 90 percent. "
            "The output beam of the laser must be shaped and directed by an optical system to "
            "generate a laser spot of desired shape and size at the correct location on the "
            "workpiece surface; reflective optical components are used as they are sturdy and "
            "easily adapted to an industrial environment."
        ),
    },
    {
        "id": "REG-23",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, describe how bonding is achieved.",
        "ground_truth": (
            "Bonding is achieved in fusion welding by interposing a liquid of substantially "
            "similar composition as the base metal between the surfaces to be joined. "
            "The need for welding and joining is substantial since only monolithic parts can "
            "be made without joining."
        ),
    },
    {
        "id": "REG-24",
        "category": "manufacturing",
        "question": "According to Modern Manufacturing, can you give me an application or example of how bonding is achieved?",
        "ground_truth": (
            "In the fabrication of heavy structures, arc welding dominates other assembly "
            "processes because of the inherent flexibility and economy of welding."
        ),
    },

    # ── Grounding / hallucination guard (no ground_truth — skipped from retrieval metrics) ──
    {
        "id": "REG-14",
        "category": "grounding",
        "question": "What is the torque specification for a Ford F-150 lug nut?",
        # No ground_truth: scores faithfulness + answer_relevancy only.
        # Tests that the system does NOT hallucinate an answer absent from the docs.
    },
    {
        'id': 'REG-25',
        'category': 'welding',
        'question': 'Why should excessive convexity be avoided in fillet welds?',
        'ground_truth': 'Excessive convexity is an undesirable fillet-weld profile; the text advises avoiding it just as excessive reinforcement should be avoided in groove welds.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 133
    },
    {
        'id': 'REG-26',
        'category': 'welding',
        'question': 'What are the four basic welding positions?',
        'ground_truth': 'Flat, horizontal, vertical, and overhead.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 137
    },
    {
        'id': 'REG-27',
        'category': 'welding',
        'question': 'Why should a welder control maximum weave width?',
        'ground_truth': 'Controlling weave width helps prevent slag inclusions and incomplete-fusion discontinuities.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 137
    },
    {
        'id': 'REG-28',
        'category': 'welding',
        'question': 'What is undercut at the toe of a fillet weld?',
        'ground_truth': 'Undercut is a groove or melting away of base metal adjacent to the weld toe, leaving a reduction in the original base-metal surface.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 144
    },
    {
        'id': 'REG-29',
        'category': 'welding',
        'question': 'What welding conditions can contribute to an undesirable weld bead profile?',
        'ground_truth': 'The chapter discusses welding current and travel rate as variables affecting weld-bead profile and weld discontinuities.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 144
    },
    {
        'id': 'REG-30',
        'category': 'welding',
        'question': 'Which trapped materials can cause weld discontinuities?',
        'ground_truth': 'Entrapped slag produces slag inclusions; entrapped gas produces porosity.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 144
    },
    {
        'id': 'REG-31',
        'category': 'welding',
        'question': 'Where can cracks occur in or around a welded joint?',
        'ground_truth': 'The illustrated crack locations include toe cracks, root cracks, crater cracks, and underbead or heat-affected-zone cracks.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 145
    },
    {
        'id': 'REG-32',
        'category': 'welding',
        'question': 'What does HAZ stand for in welding discontinuity diagrams?',
        'ground_truth': 'HAZ means heat-affected zone, the base-metal region affected by welding heat.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 145
    },
    {
        'id': 'REG-33',
        'category': 'welding',
        'question': 'Why should welders know how to identify discontinuities?',
        'ground_truth': 'Welders may need to recognize discontinuities or defects in qualification or knowledge testing and to evaluate work against welding requirements.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 149
    },
    {
        'id': 'REG-34',
        'category': 'welding',
        'question': 'Why is a welding procedure important when inspecting weld quality?',
        'ground_truth': 'The welding procedure establishes requirements for the work; applicable codes may require that a procedure be available and followed.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 149
    },
    {
        'id': 'REG-35',
        'category': 'welding',
        'question': 'What advantages does the text associate with concentrated-arc GMAW welding?',
        'ground_truth': 'The discussion associates GMAW with deep penetration, a narrow bead, a relatively small heat-affected zone, faster welding, less warpage and distortion, and reduced postweld cleaning.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 23
    },
    {
        'id': 'REG-36',
        'category': 'welding',
        'question': 'Which consumables and process variables must a welder select appropriately?',
        'ground_truth': 'The welder must select suitable electrode size and type and the correct shielding gas, and control electrode or torch angle, distance, and travel.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 26
    },
    {
        'id': 'REG-37',
        'category': 'welding',
        'question': 'How can a covered welding electrode affect deposited weld-metal properties?',
        'ground_truth': 'Electrode classification and covering influence the physical and chemical properties of deposited weld metal; some coverings also contain metal powder.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 295
    },
    {
        'id': 'REG-38',
        'category': 'welding',
        'question': 'What two fusion-related problems can result from poorly controlled weaving?',
        'ground_truth': 'Slag inclusions and incomplete fusion are two discontinuities that controlling maximum weave width can help prevent.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 137
    },
    {
        'id': 'REG-39',
        'category': 'welding',
        'question': 'How do porosity and slag inclusions differ?',
        'ground_truth': 'Porosity involves gas entrapped in deposited weld metal, while slag inclusions involve trapped nonmetallic slag.',
        # Source: Welding_Principles_Practices_Bohnart.pdf, PDF page 144
    },
    {
        'id': 'REG-40',
        'category': 'welding',
        'question': 'How does GTAW shield its weld pool from atmospheric contamination?',
        'ground_truth': 'Shielding gas flows from the GTAW torch nozzle to protect the molten weld metal from atmospheric contamination.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 42
    },
    {
        'id': 'REG-41',
        'category': 'welding',
        'question': 'How is filler metal introduced in manual GTAW?',
        'ground_truth': 'A separate filler rod can be manually dipped into the molten weld pool.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 42
    },
    {
        'id': 'REG-42',
        'category': 'welding',
        'question': 'What optional controls can be used with a GTAW machine?',
        'ground_truth': 'A foot-operated or thumb-operated remote control may be added to control the welding operation.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 42
    },
    {
        'id': 'REG-43',
        'category': 'welding',
        'question': 'What defects may result from poor arc stability in SMAW?',
        'ground_truth': 'Poor arc stability can lead to spatter, porosity, and slag inclusions.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 116
    },
    {
        'id': 'REG-44',
        'category': 'welding',
        'question': 'What happens to bead width and penetration when SMAW amperage increases?',
        'ground_truth': 'Higher amperage generally produces a wider, flatter weld bead and deeper penetration.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 116
    },
    {
        'id': 'REG-45',
        'category': 'welding',
        'question': 'Why should an SMAW welder maintain a short arc?',
        'ground_truth': 'A short arc can help obtain good fusion with fewer slag inclusions, provided current remains in the recommended electrode range.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 118
    },
    {
        'id': 'REG-46',
        'category': 'welding',
        'question': 'Why should amperage be kept within the electrode recommended range?',
        'ground_truth': 'The text advises using settings within the specified amperage range for the particular electrode while establishing an appropriate arc length.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 118
    },
    {
        'id': 'REG-47',
        'category': 'welding',
        'question': 'Why are the sides of thermally cut welding test specimens ground?',
        'ground_truth': 'Grinding removes the heat-affected zone produced by thermal cutting.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 183
    },
    {
        'id': 'REG-48',
        'category': 'welding',
        'question': 'What direction should grinding or machining marks run on a welding test specimen?',
        'ground_truth': 'Grinding or machining marks should run lengthwise along the specimen.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 183
    },
    {
        'id': 'REG-49',
        'category': 'welding',
        'question': 'What is the maximum corner radius specified in the discussed welding test specimen preparation?',
        'ground_truth': 'Corners are rounded to a maximum radius of 1/8 inch (3 mm).',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 183
    },
    {
        'id': 'REG-50',
        'category': 'welding',
        'question': 'What is the difference between porosity and inclusions as weld discontinuities?',
        'ground_truth': 'Porosity refers to voids from trapped gas; inclusions are foreign solid material trapped in the weld.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 14
    },
    {
        'id': 'REG-51',
        'category': 'welding',
        'question': 'How do inadequate joint penetration and incomplete fusion differ?',
        'ground_truth': 'Inadequate joint penetration means the weld does not extend through the required joint depth; incomplete fusion means weld metal has not fused properly with the base metal or a previous weld pass.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 14
    },
    {
        'id': 'REG-52',
        'category': 'welding',
        'question': 'Which weld discontinuities are listed alongside undercut in the quality-control chapter?',
        'ground_truth': 'The quality-control chapter lists overlap, undercut, crater cracks, underfill, porosity, and inclusions among its discontinuity topics.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 14
    },
    {
        'id': 'REG-53',
        'category': 'welding',
        'question': 'What does the Jeffus textbook call the region of base metal thermally affected by welding?',
        'ground_truth': 'The heat-affected zone (HAZ), discussed under thermal effects caused by arc welding.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 15
    },
    {
        'id': 'REG-54',
        'category': 'welding',
        'question': 'Which gases are discussed as affecting welding metallurgy?',
        'ground_truth': 'The metallurgy chapter lists nitrogen, oxygen, carbon dioxide, and hydrogen among gases in welding.',
        # Source: Welding_Principles_Applications_Jeffus.pdf, PDF page 15
    },
    {
        'id': 'REG-55',
        'category': 'manufacturing',
        'question': 'How does the weldability of mild steel compare with medium-carbon steel in the manufacturing text?',
        'ground_truth': 'The text describes mild steel with carbon limited to about 0.25% as having very good weldability; medium-carbon steel has less weldability but greater strength and wear resistance.',
        # Source: manufacturing_processes.pdf, PDF page 27
    },
    {
        'id': 'REG-56',
        'category': 'manufacturing',
        'question': 'Which cast iron is widely used for inexpensive foundry castings?',
        'ground_truth': 'Grey cast iron is described as inexpensive and widely used for foundry castings.',
        # Source: manufacturing_processes.pdf, PDF page 29
    },
    {
        'id': 'REG-57',
        'category': 'manufacturing',
        'question': 'What changes can alloying produce in cast-iron mechanical properties?',
        'ground_truth': 'Alloying can increase strength and yield point and reduce brittleness, improving the usefulness of castings.',
        # Source: manufacturing_processes.pdf, PDF page 30
    },
    {
        'id': 'REG-58',
        'category': 'manufacturing',
        'question': 'How do cold-rolled bright bars differ in appearance from hot-rolled black bars?',
        'ground_truth': 'Cold-worked bright bars have a bright finish, whereas hot-rolled black bars appear grayish-black because of surface oxidation.',
        # Source: manufacturing_processes.pdf, PDF page 46
    },
    {
        'id': 'REG-59',
        'category': 'manufacturing',
        'question': 'How can cold working affect metal strength?',
        'ground_truth': 'Cold working causes work hardening, which increases strength.',
        # Source: manufacturing_processes.pdf, PDF page 46
    },
    {
        'id': 'REG-60',
        'category': 'manufacturing',
        'question': 'Name three bulk metal-forming processes mentioned in Manufacturing Processes.',
        'ground_truth': 'Forging, rolling, and extrusion are named as metal-forming processes.',
        # Source: manufacturing_processes.pdf, PDF page 47
    },
    {
        'id': 'REG-61',
        'category': 'manufacturing',
        'question': 'What is extrusion in metal manufacturing?',
        'ground_truth': 'Extrusion forces metal to flow plastically from a confined chamber through an opening in a die, producing the required cross-sectional shape.',
        # Source: manufacturing_processes.pdf, PDF page 72
    },
    {
        'id': 'REG-62',
        'category': 'cnc',
        'question': 'What is chip load in CNC machining?',
        'ground_truth': 'Chip load is the thickness of material removed by each cutting tooth, also called feed per tooth.',
        # Source: autodesk_cncbook.pdf, PDF page 32
    },
    {
        'id': 'REG-63',
        'category': 'cnc',
        'question': 'How does chip thickness change during climb milling?',
        'ground_truth': 'In climb milling, chip thickness starts at a maximum and decreases toward zero.',
        # Source: autodesk_cncbook.pdf, PDF page 32
    },
    {
        'id': 'REG-64',
        'category': 'cnc',
        'question': 'How does chip thickness change during conventional milling?',
        'ground_truth': 'In conventional milling, chip thickness starts near zero and increases toward its maximum.',
        # Source: autodesk_cncbook.pdf, PDF page 32
    },
    {
        'id': 'REG-65',
        'category': 'cnc',
        'question': 'Why is the tool length offset important in CNC machining?',
        'ground_truth': 'A tool length offset accounts for the tool length so the control can position the tool tip correctly relative to the work coordinate system.',
        # Source: autodesk_cncbook.pdf, PDF page 50
    },
    {
        'id': 'REG-66',
        'category': 'cnc',
        'question': 'Why might speeds and feeds need reduction for a long, thin cutting tool?',
        'ground_truth': 'Long, slender tools are less rigid, so lower cutting speeds or feeds may be needed to avoid deflection and vibration.',
        # Source: autodesk_cncbook.pdf, PDF page 33
    },
    {
        'id': 'REG-67',
        'category': 'machining',
        'question': 'May a student operate in the Florida Tech machine shop without a supervisor?',
        'ground_truth': 'No. The shop rules require an approved supervisor to be present.',
        # Source: basic_machine_tool_operations_aug_2017.pdf, PDF page 3
    },
    {
        'id': 'REG-68',
        'category': 'machining',
        'question': 'What does the Florida Tech shop require for eye protection?',
        'ground_truth': 'Safety glasses must be worn at all times; tinted glasses or sunglasses are not permitted as substitutes.',
        # Source: basic_machine_tool_operations_aug_2017.pdf, PDF page 3
    },
    {
        'id': 'REG-69',
        'category': 'machining',
        'question': 'Who must inspect a machine setup before operation?',
        'ground_truth': 'The supervisor must check machine setups before machine operation begins.',
        # Source: basic_machine_tool_operations_aug_2017.pdf, PDF page 3
    },
    {
        'id': 'REG-70',
        'category': 'lean-manufacturing',
        'question': 'How does the Boeing lean study define the central objective of lean manufacturing?',
        'ground_truth': 'Lean manufacturing systematically eliminates waste while emphasizing production cost, product quality and delivery, and worker involvement.',
        # Source: boeing_lean_manufacturing_studies.pdf, PDF page 4
    },
    {
        'id': 'REG-71',
        'category': 'lean-manufacturing',
        'question': 'What transportation and handling improvements were reported for the Boeing floor-beam shipping value chain?',
        'ground_truth': 'The report describes elimination of eight days of travel and three days of receiving and inspection, with approximately 50% less transportation per ship set.',
        # Source: boeing_lean_manufacturing_studies.pdf, PDF page 15
    },
    {
        'id': 'REG-72',
        'category': 'lean-manufacturing',
        'question': 'What is an AIW in the Boeing Auburn lean-improvement discussion?',
        'ground_truth': 'An AIW is an accelerated improvement workshop, used for focused waste-elimination improvements; the report notes multiple workshops scheduled monthly.',
        # Source: boeing_lean_manufacturing_studies.pdf, PDF page 23
    },
    {
        'id': 'REG-73',
        'category': 'maintenance',
        'question': 'How does the C4ISR maintenance manual describe preventive maintenance for generators?',
        'ground_truth': 'Preventive maintenance involves periodic checking and testing of equipment, with tasks and frequency specified in maintenance tables.',
        # Source: c4isr_maintenance_practices.pdf, PDF page 147
    },
    {
        'id': 'REG-74',
        'category': 'maintenance',
        'question': 'What kinds of control instruments should be checked for calibration during maintenance?',
        'ground_truth': 'Transmitters, sensing elements, temperature and pressure switches, time-delay relays, indicators, and recorders are among the items listed.',
        # Source: c4isr_maintenance_practices.pdf, PDF page 95
    },
]

# ── Behavioral test cases ─────────────────────────────────────────────────────
# These verify routing, guard, and clarification logic.
# Pass/fail is determined by assertions on the response shape — no Ragas scoring.
# Each entry has:
#   id          (str)  – unique identifier
#   description (str)  – what routing/behavioral path is being tested
#   question    (str)  – message sent to the chatbot
#   checks      (list) – assertion dicts; each has a "type" key and optional "value"
#
# Check types:
#   reply_contains   – reply.lower() contains value.lower()
#   reply_nonempty   – reply is non-empty
#   sources_empty    – sources list is empty
#   sources_nonempty – sources list has at least one entry
#   no_clarification – metadata has no "clarification" key
#   has_clarification – metadata has a "clarification" key

BEHAVIORAL_TESTS: list[dict] = [
    {
        "id": "BEH-01",
        "description": "Off-topic guard: entertainment request is blocked by fast-check",
        # "Tell me a joke" hits the whole-word fast-check on 'joke' deterministically,
        # without requiring an LLM call — making this a reliable, variance-free assertion.
        "question": "Tell me a joke",
        "checks": [
            {"type": "reply_contains", "value": "I can only answer questions about the uploaded documents"},
            {"type": "sources_empty"},
            {"type": "no_clarification"},
        ],
    },
    {
        "id": "BEH-02",
        "description": "Broad path: 'across all documents' phrase triggers multi-doc answer",
        "question": "Across all documents, what types of safety equipment or protective gear are mentioned?",
        "checks": [
            {"type": "reply_nonempty"},
            {"type": "sources_nonempty"},
            {"type": "no_clarification"},
        ],
    },
    {
        "id": "BEH-03",
        "description": "Ambiguous path: cross-cutting question triggers clarification flow",
        # "What safety gear do I need to wear?" matches multiple docs (CNC shop, machine
        # tool operations, etc.) competitively — confirmed to trigger clarification in the app.
        "question": "What safety gear do I need to wear?",
        "checks": [
            {"type": "has_clarification"},
            {"type": "sources_empty"},
        ],
    },
    {
        "id": "BEH-04",
        "description": "Pass path: specific single-doc question returns answer with sources",
        # The machine shop certification content appears only in the Basic Machine Tool
        # Operations doc, so this should resolve cleanly without triggering clarification.
        "question": "How do I get my machine shop student certification?",
        "checks": [
            {"type": "reply_nonempty"},
            {"type": "sources_nonempty"},
            {"type": "no_clarification"},
        ],
    },
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _send(question: str, session_id: str = "regression_session") -> dict:
    """POST a question to /chat and return the parsed JSON response."""
    resp = API_SESSION.post(
        CHAT_URL,
        json={"message": question, "session_id": session_id},
        headers={"X-Tab-ID": TAB_ID},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()

def _login():
    """Initialize an API browser session and log in the regression tab."""
    username = os.getenv("REGRESSION_USERNAME")
    password = os.getenv("REGRESSION_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "Set REGRESSION_USERNAME and REGRESSION_PASSWORD to the test account credentials."
        )

    headers = {"X-Tab-ID": TAB_ID}
    bootstrap = API_SESSION.post(SESSION_URL, headers=headers, timeout=10)
    bootstrap.raise_for_status()

    resp = API_SESSION.post(
        LOGIN_URL,
        json={"username": username, "password": password},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("user_id")


def _clear_session(session_id: str = "regression_session") -> None:
    resp = API_SESSION.post(
        CLEAR_URL,
        json={"session_id": session_id},
        headers={"X-Tab-ID": TAB_ID},
        timeout=10,
    )
    resp.raise_for_status()


def _check_backend() -> tuple[bool, str]:
    """Return (reachable, message)."""
    try:
        r = requests.get("http://localhost:5000/api/health", timeout=5)
        return r.status_code == 200, r.text
    except requests.RequestException as exc:
        return False, str(exc)


# ── Output collection ─────────────────────────────────────────────────────────

def collect_rag_outputs(tests: list[dict], pause: float = 0.5) -> list[dict]:
    """
    Run each test question through the chatbot and collect:
      - the generated answer
      - the retrieved context chunks (``full_snippet`` or ``snippet`` per source)

    Returns a list of enriched dicts, one per test, adding:
        answer   (str)        – the chatbot's reply
        contexts (list[str])  – text of every retrieved chunk
        sources  (list[dict]) – raw source metadata from the API
        error    (str|None)   – exception message if the call failed
        response_time_s (float)
    """
    results: list[dict] = []

    for test in tests:
        session_id = f"regression_{test['id']}"
        _clear_session(session_id)
        time.sleep(pause)

        print(f"  [{test['id']}] {test['question'][:70]}...")
        t0 = time.time()
        row = dict(test)  # copy to avoid mutating the original

        try:
            resp     = _send(test["question"], session_id=session_id)
            elapsed  = time.time() - t0
            answer   = resp.get("reply", "")
            sources  = resp.get("metadata", {}).get("sources", [])

            # Use full_snippet when available; fall back to snippet.
            # No truncation — the Ragas LLM (gpt-4o-mini, max_tokens=8192) can
            # handle full-length chunks without hitting output token limits.
            contexts = [
                s.get("full_snippet") or s.get("snippet", "")
                for s in sources
                if s.get("full_snippet") or s.get("snippet")
            ]

            row.update({
                "answer":           answer,
                "contexts":         contexts,
                "sources":          sources,
                "response_time_s":  round(elapsed, 2),
                "error":            None,
            })
            print(f"       → {elapsed:.1f}s  |  {len(contexts)} context chunk(s) retrieved")

        except Exception as exc:
            elapsed = time.time() - t0
            row.update({
                "answer":           "",
                "contexts":         [],
                "sources":          [],
                "response_time_s":  round(elapsed, 2),
                "error":            str(exc),
            })
            print(f"       → ERROR: {exc}")

        results.append(row)
        print()

    return results


# ── Evaluation + reporting ────────────────────────────────────────────────────

def run_behavioral_tests(tests: list[dict], pause: float = 0.5) -> list[dict]:
    """
    Run behavioral assertion tests against the live backend.

    Each test sends a question and checks the response shape against a list of
    assertions.  No Ragas scoring is performed — pass/fail is determined purely
    by the structure of the backend's JSON response.

    Returns a list of result dicts, one per test, with keys:
        id          (str)   – test identifier
        description (str)   – what is being tested
        passed      (bool)  – True if all checks passed
        failures    (list)  – human-readable failure messages
        error       (str|None) – exception message if the HTTP call failed
    """
    results: list[dict] = []

    for test in tests:
        session_id = f"regression_{test['id']}"
        _clear_session(session_id)
        time.sleep(pause)

        print(f"  [{test['id']}] {test['description']}")
        t0 = time.time()
        result: dict = {
            "id":          test["id"],
            "description": test["description"],
            "passed":      True,
            "failures":    [],
            "error":       None,
        }

        try:
            resp          = _send(test["question"], session_id=session_id)
            elapsed       = time.time() - t0
            reply         = resp.get("reply", "")
            metadata      = resp.get("metadata", {})
            sources       = metadata.get("sources", [])
            clarification = metadata.get("clarification")

            failures: list[str] = []
            for check in test.get("checks", []):
                ctype = check["type"]
                if ctype == "reply_contains":
                    if check["value"].lower() not in reply.lower():
                        failures.append(
                            f"reply_contains: expected '{check['value']}' in reply; "
                            f"got: '{reply[:120]}'"
                        )
                elif ctype == "reply_nonempty":
                    if not reply.strip():
                        failures.append("reply_nonempty: reply was empty")
                elif ctype == "sources_empty":
                    if sources:
                        failures.append(
                            f"sources_empty: expected no sources, got {len(sources)}"
                        )
                elif ctype == "sources_nonempty":
                    if not sources:
                        failures.append(
                            "sources_nonempty: expected at least one source, got none"
                        )
                elif ctype == "no_clarification":
                    if clarification:
                        failures.append(
                            "no_clarification: unexpected clarification metadata in response"
                        )
                elif ctype == "has_clarification":
                    if not clarification:
                        failures.append(
                            "has_clarification: expected clarification metadata but none present"
                        )

            result["passed"]   = len(failures) == 0
            result["failures"] = failures
            status = "PASS" if result["passed"] else "FAIL"
            print(f"       → {elapsed:.1f}s  |  {status}")
            for msg in failures:
                print(f"         ✗ {msg}")

        except Exception as exc:
            result["passed"] = False
            result["error"]  = str(exc)
            print(f"       → ERROR: {exc}")

        results.append(result)
        print()

    return results


def _evaluate(
    collected: list[dict],
    thresholds: dict[str, float],
) -> tuple[dict[str, float], list[str]]:
    """
    Score the collected outputs with Ragas and return (scores, failures).

    Faithfulness + answer_relevancy are computed for every scoreable row.
    Context_precision + context_recall are computed only for rows that have
    a non-empty ``ground_truth`` value (rows without one, e.g. the hallucination
    guard test REG-14, are excluded from retrieval metric averaging).

    ``failures`` is a list of human-readable failure messages for metrics
    that fell below their threshold.
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from ragas_eval import score_outputs, print_score_table  # type: ignore

    # Base filter: no errors, has an answer and at least one context chunk
    scoreable = [
        r for r in collected
        if not r.get("error") and r.get("answer") and r.get("contexts")
    ]

    if not scoreable:
        print(
            "\n[WARNING] No scoreable rows — all test questions either errored "
            "or returned no context chunks.  Skipping Ragas evaluation."
        )
        return {}, []

    skipped = len(collected) - len(scoreable)
    if skipped:
        print(f"\n[INFO] Skipping {skipped} row(s) with errors or empty contexts.")

    # Rows with ground_truth → eligible for all 4 metrics
    retrieval_rows = [r for r in scoreable if r.get("ground_truth")]
    grounding_only_rows = [r for r in scoreable if not r.get("ground_truth")]

    if grounding_only_rows:
        ids = [r["id"] for r in grounding_only_rows]
        print(f"[INFO] {len(grounding_only_rows)} row(s) have no ground_truth and will be "
              f"scored for faithfulness + answer_relevancy only: {ids}")

    all_scores: dict[str, float] = {}

    # Pass 1 — grounding metrics across ALL scoreable rows
    print(f"\nRunning grounding metrics (faithfulness, answer_relevancy) "
          f"on {len(scoreable)} row(s) ...")
    grounding_scores = score_outputs(scoreable, include_retrieval_metrics=False)
    all_scores.update(grounding_scores)

    # Pass 2 — retrieval metrics only for rows WITH ground_truth
    if retrieval_rows:
        print(f"Running retrieval metrics (context_precision, context_recall) "
              f"on {len(retrieval_rows)} row(s) ...\n")
        retrieval_scores = score_outputs(retrieval_rows, include_retrieval_metrics=True)
        # Keep only the retrieval-specific metrics from this pass
        for k in ("context_precision", "context_recall"):
            if k in retrieval_scores:
                all_scores[k] = retrieval_scores[k]
    else:
        print("[INFO] No rows with ground_truth — skipping retrieval metrics.")

    print_score_table(all_scores, thresholds=thresholds)

    failures = [
        f"{metric}: {score:.4f} < threshold {thresholds[metric]:.2f}"
        for metric, score in all_scores.items()
        if metric in thresholds and score < thresholds[metric]
    ]
    return all_scores, failures


def _save_results(collected: list[dict], scores: dict, timestamp: str) -> str:
    """Persist raw outputs + Ragas scores to a JSON file."""
    payload = {
        "timestamp":       timestamp,
        "ragas_scores":    scores,
        "test_results":    collected,
    }
    path = os.path.join(RESULTS_DIR, f"regression_results_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path


# ── Main entry point ──────────────────────────────────────────────────────────

def run_regression(thresholds: dict[str, float], no_fail: bool = False) -> int:
    """
    Full regression pipeline:
      1. Check that the backend is reachable.
      2. Send all REGRESSION_TESTS to /chat.
      3. Run BEHAVIORAL_TESTS (routing, guard, clarification assertions).
      4. Evaluate RAG outputs with Ragas.
      5. Print a summary report.
      6. Return exit code 0 (all pass) or 1 (at least one failure).

    If ``no_fail`` is True, always return 0 (informational run).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    divider   = "=" * 65

    print(f"\n{divider}")
    print(f"  REGRESSION TEST PIPELINE  —  {datetime.now().isoformat()}")
    print(f"  {len(REGRESSION_TESTS)} RAG tests  |  {len(BEHAVIORAL_TESTS)} behavioral tests  |  4 Ragas metrics")
    print(f"  Thresholds: { {k: f'{v:.2f}' for k, v in thresholds.items()} }")
    print(f"{divider}\n")

    # 1 — Backend health check
    ok, msg = _check_backend()
    if not ok:
        print(
            f"[FATAL] Flask backend is not reachable at {CHAT_URL}\n"
            f"        Start it with:  cd backend && python run.py\n"
            f"        Error: {msg}"
        )
        return 1

    print(f"[OK] Backend reachable.\n")

    try:
        _login()
    except (requests.RequestException, RuntimeError) as exc:
        print(f"[FATAL] Could not authenticate the regression test account: {exc}")
        return 1

    print("[OK] Regression test account authenticated.\n")

    # 2 — Collect RAG outputs
    print("── Collecting answers from chatbot ──────────────────────────\n")
    collected = collect_rag_outputs(REGRESSION_TESTS)

    # 3 — Behavioral assertions (fast, no LLM judge)
    print("── Behavioral assertions ────────────────────────────────────\n")
    beh_results  = run_behavioral_tests(BEHAVIORAL_TESTS)
    beh_failures = [r for r in beh_results if not r["passed"]]

    # 4 — Ragas evaluation
    print("── Ragas scoring ────────────────────────────────────────────")
    scores, ragas_failures = _evaluate(collected, thresholds)

    # 5 — Persist
    path = _save_results(collected, scores, timestamp)
    print(f"Results saved → {path}")

    # 6 — Summary
    any_failure = bool(ragas_failures) or bool(beh_failures)
    print(f"\n{divider}")
    if not scores:
        print("  [SKIP] No Ragas scores computed — check errors above.")
        if beh_failures:
            print(f"  {len(beh_failures)} behavioral test(s) also failed:")
            for r in beh_failures:
                print(f"    • [{r['id']}] {r['description']}")
        return 1 if not no_fail else 0

    if any_failure:
        print("  RESULT: FAILED")
        if ragas_failures:
            print("  Ragas metrics below threshold:")
            for f in ragas_failures:
                print(f"    • {f}")
        if beh_failures:
            print("  Behavioral tests failed:")
            for r in beh_failures:
                print(f"    • [{r['id']}] {r['description']}")
                for msg in r["failures"]:
                    print(f"        ✗ {msg}")
    else:
        print("  RESULT: PASSED  — all Ragas metrics and behavioral tests passed.")
    print(f"{divider}\n")

    if any_failure and not no_fail:
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RAG regression test pipeline using Ragas evaluation."
    )
    p.add_argument(
        "--no-fail",
        action="store_true",
        help="Report scores but always exit 0 (informational run).",
    )
    p.add_argument(
        "--faithfulness",
        type=float,
        default=DEFAULT_THRESHOLDS["faithfulness"],
        metavar="SCORE",
        help=f"Faithfulness threshold (default: {DEFAULT_THRESHOLDS['faithfulness']}).",
    )
    p.add_argument(
        "--answer-relevancy",
        type=float,
        default=DEFAULT_THRESHOLDS["answer_relevancy"],
        metavar="SCORE",
        help=f"Answer relevancy threshold (default: {DEFAULT_THRESHOLDS['answer_relevancy']}).",
    )
    p.add_argument(
        "--context-precision",
        type=float,
        default=DEFAULT_THRESHOLDS["context_precision"],
        metavar="SCORE",
        help=f"Context precision threshold (default: {DEFAULT_THRESHOLDS['context_precision']}).",
    )
    p.add_argument(
        "--context-recall",
        type=float,
        default=DEFAULT_THRESHOLDS["context_recall"],
        metavar="SCORE",
        help=f"Context recall threshold (default: {DEFAULT_THRESHOLDS['context_recall']}).",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    thresholds = {
        "faithfulness":      args.faithfulness,
        "answer_relevancy":  args.answer_relevancy,
        "context_precision": args.context_precision,
        "context_recall":    args.context_recall,
    }

    sys.exit(run_regression(thresholds=thresholds, no_fail=args.no_fail))
