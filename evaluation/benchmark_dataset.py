"""
Perfusion AI - Comprehensive Gold-Standard Evaluation Benchmark Dataset
Contains 25 positive clinical perfusion questions across core sub-domains and
5 negative control (out-of-scope) questions to test anti-hallucination specificity.
"""

BENCHMARK_CASES = [
    # ----------------------------------------------------
    # 1. ANTICOAGULATION & HEMOSTASIS (5 cases)
    # ----------------------------------------------------
    {
        "id": "CASE-01",
        "category": "Anticoagulation",
        "question": "What is the target Activated Clotting Time (ACT) before initiating cardiopulmonary bypass?",
        "is_positive": True,
        "expected_keywords": ["400", "480", "seconds", "act", "heparin"],
        "expected_facts": [
            "Baseline ACT is approximately 100-140 seconds.",
            "ACT must exceed 400 to 480 seconds before initiating CPB.",
            "Heparin must be fully circulated before aortic or venous cannulation."
        ]
    },
    {
        "id": "CASE-02",
        "category": "Anticoagulation",
        "question": "What is the standard initial heparin dosing regimen for cardiopulmonary bypass?",
        "is_positive": True,
        "expected_keywords": ["300", "400", "units/kg", "mg/kg", "unfractionated"],
        "expected_facts": [
            "Standard loading dose is 300 to 400 units/kg (approx 3 to 4 mg/kg) of unfractionated heparin.",
            "Administered centrally to ensure rapid systemic circulation."
        ]
    },
    {
        "id": "CASE-03",
        "category": "Anticoagulation",
        "question": "How is protamine dosed to neutralize heparin after weaning from cardiopulmonary bypass?",
        "is_positive": True,
        "expected_keywords": ["protamine", "1 mg", "1.3 mg", "100 units", "reversal", "sulfate"],
        "expected_facts": [
            "Protamine sulfate is dosed at approximately 1 to 1.3 mg per 100 units of initial heparin.",
            "Slow infusion over 10-15 minutes to prevent catastrophic hypotension and pulmonary hypertension."
        ]
    },
    {
        "id": "CASE-04",
        "category": "Anticoagulation",
        "question": "What causes heparin resistance during CPB and how is it clinically managed?",
        "is_positive": True,
        "expected_keywords": ["antithrombin", "at-iii", "fresh frozen plasma", "ffp", "concentrate", "resistance"],
        "expected_facts": [
            "Heparin resistance is primarily caused by Antithrombin III (AT-III) deficiency.",
            "Prior preoperative heparin therapy, nitroglycerin, or congenital deficiency decrease AT-III.",
            "Managed with additional heparin, Fresh Frozen Plasma (FFP), or recombinant/purified AT-III concentrate."
        ]
    },
    {
        "id": "CASE-05",
        "category": "Anticoagulation",
        "question": "How does Heparin-Induced Thrombocytopenia (HIT) affect perfusion management and what alternatives are used?",
        "is_positive": True,
        "expected_keywords": ["bivalirudin", "argatroban", "hit", "thrombocytopenia", "direct thrombin"],
        "expected_facts": [
            "HIT is an immune-mediated disorder caused by antibodies to platelet factor 4 (PF4)-heparin complexes.",
            "Direct thrombin inhibitors (DTIs) such as bivalirudin or argatroban are used as alternatives.",
            "Bivalirudin requires monitoring ecarin clotting time (ECT) or elevated ACT."
        ]
    },

    # ----------------------------------------------------
    # 2. OXYGENATORS & GAS EXCHANGE (4 cases)
    # ----------------------------------------------------
    {
        "id": "CASE-06",
        "category": "Oxygenators",
        "question": "How do membrane oxygenators regulate arterial PaO2 and carbon dioxide (PaCO2) elimination during CPB?",
        "is_positive": True,
        "expected_keywords": ["fio2", "sweep", "gas", "oxygen", "carbon dioxide", "paco2", "pao2"],
        "expected_facts": [
            "PaO2 is controlled by adjusting the FiO2 blender on the gas mixer.",
            "PaCO2 is controlled by adjusting the sweep gas flow rate through the membrane.",
            "Increasing sweep gas increases CO2 clearance and lowers arterial PaCO2."
        ]
    },
    {
        "id": "CASE-07",
        "category": "Oxygenators",
        "question": "What materials are utilized in modern hollow-fiber membrane oxygenators?",
        "is_positive": True,
        "expected_keywords": ["polypropylene", "polymethylpentene", "pmp", "microporous", "hollow-fiber"],
        "expected_facts": [
            "Hollow-fiber microporous polypropylene is standard for short-term CPB.",
            "Polymethylpentene (PMP) non-porous/diffusion membranes are preferred for extended CPB and ECMO to prevent plasma leakage."
        ]
    },
    {
        "id": "CASE-08",
        "category": "Oxygenators",
        "question": "What are the signs of acute membrane oxygenator failure during cardiopulmonary bypass?",
        "is_positive": True,
        "expected_keywords": ["transmembrane pressure", "tmp", "gradient", "exhaust", "desaturation", "plasma"],
        "expected_facts": [
            "Progressive post-oxygenator arterial desaturation despite high FiO2.",
            "Sharp increase in transmembrane pressure gradient (TMP > 100-150 mmHg).",
            "Visible clot or wet/plasma wetting of the exhaust ports."
        ]
    },
    {
        "id": "CASE-09",
        "category": "Oxygenators",
        "question": "What is the recommended ratio of sweep gas flow to blood flow on initiation of bypass?",
        "is_positive": True,
        "expected_keywords": ["1:1", "0.8:1", "ratio", "sweep", "blood flow"],
        "expected_facts": [
            "Initial sweep gas to blood flow ratio is typically 0.8:1 to 1:1 in adults.",
            "Adjusted based on serial inline or laboratory arterial blood gas PaCO2."
        ]
    },

    # ----------------------------------------------------
    # 3. PUMPS & MECHANICAL CIRCUITRY (4 cases)
    # ----------------------------------------------------
    {
        "id": "CASE-10",
        "category": "Pumps & Hardware",
        "question": "Compare centrifugal blood pumps with positive-displacement roller pumps in CPB circuits.",
        "is_positive": True,
        "expected_keywords": ["centrifugal", "roller", "afterload", "occlusion", "preload", "cavitation", "hemolysis"],
        "expected_facts": [
            "Roller pumps are positive displacement pumps; flow is strictly determined by RPM and boot size, independent of line resistance.",
            "Centrifugal pumps use rotating impellers/cones; flow is afterload-dependent and preload-dependent.",
            "Centrifugal pumps cannot build dangerous high pressures upon line occlusion and cannot pump massive air under moderate resistance."
        ]
    },
    {
        "id": "CASE-11",
        "category": "Pumps & Hardware",
        "question": "What is the procedure for setting roller pump occlusion before initiating CPB?",
        "is_positive": True,
        "expected_keywords": ["occlusion", "roller", "fluid drop", "barely nonocclusive", "hemolysis", "gap"],
        "expected_facts": [
            "Adjusted by dynamic fluid level drop rate (e.g. 1 cm/min at 1000 mm fluid column) or static pressure hold.",
            "Set to barely non-occlusive to minimize hemolysis and tubing spallation."
        ]
    },
    {
        "id": "CASE-12",
        "category": "Pumps & Hardware",
        "question": "What role does the arterial line filter play in a cardiopulmonary bypass circuit?",
        "is_positive": True,
        "expected_keywords": ["filter", "microns", "20", "40", "microemboli", "screen", "depth"],
        "expected_facts": [
            "Placed distal to the oxygenator to trap particulate debris and gaseous microemboli.",
            "Pore size is typically 20 to 43 microns.",
            "Includes a continuous purge line to vent accumulated air back to the cardiotomy reservoir."
        ]
    },
    {
        "id": "CASE-13",
        "category": "Pumps & Hardware",
        "question": "What are the advantages and pressure limits of Vacuum-Assisted Venous Drainage (VAVD)?",
        "is_positive": True,
        "expected_keywords": ["vavd", "vacuum", "venous", "drainage", "-40", "-60", "mmhg", "negative pressure"],
        "expected_facts": [
            "Enables smaller venous cannula diameters and minimally invasive incisions.",
            "Negative pressure is strictly regulated between -30 to -60 mmHg.",
            "Excessive vacuum (> -80 mmHg) causes hemolysis and circuit cavitation."
        ]
    },

    # ----------------------------------------------------
    # 4. MYOCARDIAL PROTECTION & CARDIOPLEGIA (4 cases)
    # ----------------------------------------------------
    {
        "id": "CASE-14",
        "category": "Myocardial Protection",
        "question": "What is the physiological mechanism of cardioplegic arrest using hyperkalemic solutions?",
        "is_positive": True,
        "expected_keywords": ["potassium", "depolarization", "diastolic", "arrest", "membrane", "atp"],
        "expected_facts": [
            "Elevated extracellular potassium (15-30 mEq/L) reduces the resting transmembrane potential.",
            "Inactivates fast inward sodium channels, preventing phase 0 depolarization.",
            "Arrests the heart in electromechanical diastole, preserving myocardial ATP stores."
        ]
    },
    {
        "id": "CASE-15",
        "category": "Myocardial Protection",
        "question": "What is the composition and delivery strategy of del Nido cardioplegia?",
        "is_positive": True,
        "expected_keywords": ["del nido", "lidocaine", "magnesium", "mannitol", "plasma-lyte", "1:4", "single-dose"],
        "expected_facts": [
            "Base solution is Plasma-Lyte A mixed with 1 part blood to 4 parts crystalloid (1:4 ratio).",
            "Contains lidocaine (fast Na+ channel blocker), magnesium (calcium antagonist), and mannitol (osmotic agent).",
            "Administered cold as a single large dose (20 mL/kg) providing up to 60-90 minutes of protection."
        ]
    },
    {
        "id": "CASE-16",
        "category": "Myocardial Protection",
        "question": "Compare antegrade and retrograde cardioplegia administration routes.",
        "is_positive": True,
        "expected_keywords": ["antegrade", "retrograde", "coronary sinus", "aortic root", "insufficiency", "ostial"],
        "expected_facts": [
            "Antegrade cardioplegia is delivered via the aortic root or coronary ostia; distributes via coronary arteries.",
            "Retrograde cardioplegia is delivered via a balloon-tipped cannula in the coronary sinus; flows backward via cardiac veins.",
            "Retrograde is essential in severe aortic regurgitation or critical coronary artery stenosis."
        ]
    },
    {
        "id": "CASE-17",
        "category": "Myocardial Protection",
        "question": "What is Buckberg cardioplegia and how is the 4:1 blood-to-crystalloid regimen delivered?",
        "is_positive": True,
        "expected_keywords": ["buckberg", "4:1", "warm induction", "cold maintenance", "warm reperfusion", "hot shot"],
        "expected_facts": [
            "4:1 ratio of oxygenated blood to hyperkalemic crystalloid additive.",
            "Multidose protocol: warm induction, cold maintenance every 15-20 minutes, and terminal warm substrate-enriched reperfusion ('hot shot')."
        ]
    },

    # ----------------------------------------------------
    # 5. TEMPERATURE & METABOLISM (4 cases)
    # ----------------------------------------------------
    {
        "id": "CASE-18",
        "category": "Temperature Management",
        "question": "Explain the difference between alpha-stat and pH-stat arterial blood gas management during hypothermia.",
        "is_positive": True,
        "expected_keywords": ["alpha-stat", "ph-stat", "temperature", "uncorrected", "corrected", "cerebral", "autoregulation"],
        "expected_facts": [
            "Alpha-stat measures ABG at 37°C without temperature correction; maintains cellular neutrality (pH ~7.40) and preserves cerebral autoregulation in adults.",
            "pH-stat corrects for the patient's actual core temperature (adding CO2 to maintain pH 7.40 at hypothermia); enhances cerebral blood flow and brain cooling in pediatrics."
        ]
    },
    {
        "id": "CASE-19",
        "category": "Temperature Management",
        "question": "What target temperatures define Deep Hypothermic Circulatory Arrest (DHCA)?",
        "is_positive": True,
        "expected_keywords": ["18", "20", "dhca", "circulatory arrest", "deep hypothermia", "q10"],
        "expected_facts": [
            "DHCA core cooling target is typically 18°C to 20°C (tympanic/nasopharyngeal/bladder).",
            "Reduces cerebral metabolic rate of oxygen (CMRO2) to approximately 15-20% of normothermic baseline."
        ]
    },
    {
        "id": "CASE-20",
        "category": "Temperature Management",
        "question": "How does core body temperature influence minimal pump flow rate (MPFR) during CPB?",
        "is_positive": True,
        "expected_keywords": ["temperature", "mpfr", "flow rate", "oxygen consumption", "metabolism", "decrease"],
        "expected_facts": [
            "Whole body O2 consumption decreases linearly with hypothermia (Q10 of 2.6 to 3.6).",
            "At 28°C, metabolic demand drops by ~50%, allowing target pump flows to decrease safely to 1.6-1.8 L/min/m²."
        ]
    },
    {
        "id": "CASE-21",
        "category": "Temperature Management",
        "question": "What is the maximum recommended water-to-blood temperature gradient during rewarming on CPB?",
        "is_positive": True,
        "expected_keywords": ["gradient", "10", "4", "37", "rewarming", "gas", "outgassing"],
        "expected_facts": [
            "The water-to-blood temperature gradient should not exceed 10°C to prevent outgassing and microemboli.",
            "Arterial outlet temperature should not exceed 37°C (maximum 37.5°C) to prevent cerebral hyperthermia."
        ]
    },

    # ----------------------------------------------------
    # 6. PRIMING, DILUTION & EMERGENCY MANAGEMENT (4 cases)
    # ----------------------------------------------------
    {
        "id": "CASE-22",
        "category": "Perfusion Emergencies",
        "question": "What are the immediate perfusionist actions upon detecting massive air in the arterial line during CPB?",
        "is_positive": True,
        "expected_keywords": ["pump off", "clamp", "arterial line", "trendelenburg", "de-air", "purge"],
        "expected_facts": [
            "Immediately stop the arterial pump and clamp the arterial line.",
            "Inform surgeon and place patient in steep Trendelenburg position.",
            "Vent or purge the arterial circuit via the arterial filter purge line before resuming forward flow."
        ]
    },
    {
        "id": "CASE-23",
        "category": "Perfusion Emergencies",
        "question": "What clinical conditions cause sudden high arterial line pressure during cardiopulmonary bypass?",
        "is_positive": True,
        "expected_keywords": ["aortic dissection", "kink", "cannula", "resistance", "line pressure", "clamp"],
        "expected_facts": [
            "Aortic cannula malposition or acute intraoperative aortic dissection.",
            "Accidental cross-clamp on the arterial line or mechanical tubing kink.",
            "Severe peripheral vasoconstriction or cold agglutinin sludging."
        ]
    },
    {
        "id": "CASE-24",
        "category": "Prime & Dilution",
        "question": "What is the typical composition of an adult cardiopulmonary bypass circuit prime?",
        "is_positive": True,
        "expected_keywords": ["crystalloid", "plasmalyte", "normosol", "mannitol", "heparin", "bicarbonate"],
        "expected_facts": [
            "Balanced crystalloid (Plasma-Lyte A or Normosol-R, 1000-1500 mL).",
            "Mannitol (12.5-25 g) for osmotic diuresis and free-radical scavenging.",
            "Heparin (5000-10,000 units) to prevent contact pathway activation on artificial circuit surfaces.",
            "Sodium bicarbonate to buffer acidic prime."
        ]
    },
    {
        "id": "CASE-25",
        "category": "Prime & Dilution",
        "question": "What is the minimum acceptable hematocrit (Hct) threshold on cardiopulmonary bypass?",
        "is_positive": True,
        "expected_keywords": ["hematocrit", "20", "22", "24", "dilution", "rbc"],
        "expected_facts": [
            "Target on-bypass hematocrit is typically maintained between 21% and 25%.",
            "Hct below 20-21% impairs critical oxygen delivery (DO2) and warrants packed red blood cell (PRBC) addition or ultrafiltration."
        ]
    },

    # ----------------------------------------------------
    # 7. NEGATIVE CONTROLS (5 out-of-scope queries)
    # Strict anti-hallucination test: must reject or state insufficient evidence
    # ----------------------------------------------------
    {
        "id": "NEG-01",
        "category": "Negative Control (Dermatology)",
        "question": "What are the first-line systemic biologic therapies for moderate-to-severe plaque psoriasis with psoriatic arthritis?",
        "is_positive": False,
        "expected_keywords": [],
        "expected_facts": [
            "The system must refuse to answer and explicitly state insufficient supporting evidence in indexed perfusion documents."
        ]
    },
    {
        "id": "NEG-02",
        "category": "Negative Control (General Surgery)",
        "question": "How is the Critical View of Safety achieved during a laparoscopic cholecystectomy for gallstones?",
        "is_positive": False,
        "expected_keywords": [],
        "expected_facts": [
            "The system must refuse to answer and cite no unsupported surgical techniques outside perfusion."
        ]
    },
    {
        "id": "NEG-03",
        "category": "Negative Control (Physics)",
        "question": "Explain the derivation of the Schwarzschild metric from Einstein's vacuum field equations in general relativity.",
        "is_positive": False,
        "expected_keywords": [],
        "expected_facts": [
            "The system must refuse to answer and state insufficient evidence in perfusion documents."
        ]
    },
    {
        "id": "NEG-04",
        "category": "Negative Control (Computer Science)",
        "question": "What is the mathematical proof of preimage and collision resistance in SHA-256 cryptographic hashing algorithms?",
        "is_positive": False,
        "expected_keywords": [],
        "expected_facts": [
            "The system must refuse to answer and state insufficient evidence in perfusion documents."
        ]
    },
    {
        "id": "NEG-05",
        "category": "Negative Control (Plant Biology)",
        "question": "Explain the Z-scheme electron transport chain and oxygen-evolving complex of photosystem II in plant thylakoids.",
        "is_positive": False,
        "expected_keywords": [],
        "expected_facts": [
            "The system must refuse to answer and state insufficient evidence in perfusion documents."
        ]
    }
]

