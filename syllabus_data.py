"""
UPSC source taxonomy: standard NCERT books (with real chapter lists) and the
common reference books mapped to subjects and topics.

Used to drive the NCERT MCQs section (book -> chapter) and to ground AI question
generation in a specific, well-known source so the questions stay on-syllabus.

Covers the standard subject-wise NCERT 6th-12th booklist used for UPSC prep.
Kept as plain Python data (no DB) so it loads instantly and is easy to extend:
just add a book dict to NCERT_BOOKS or a subject/topic to REFERENCE_BOOKS.
"""

# ── NCERT books, grouped by subject, each with its chapter list ────────────────
# `key` is a short stable id used by the API/frontend. `subject` lines up with the
# subjects used elsewhere in the app so analytics stay consistent.
NCERT_BOOKS = [
    {
        "key": "hist6_our_pasts_1", "book": "Our Pasts I (Class 6)",
        "subject": "Ancient History", "grade": "Class 6",
        "read_url": "archive:ncert-fess1",
        "chapters": [
            "What, Where, How and When?",
            "From Hunting-Gathering to Growing Food",
            "In the Earliest Cities",
            "What Books and Burials Tell Us",
            "Kingdoms, Kings and an Early Republic",
            "New Questions and Ideas",
            "Ashoka, the Emperor Who Gave Up War",
            "Vital Villages, Thriving Towns",
            "Traders, Kings and Pilgrims",
            "New Empires and Kingdoms",
            "Buildings, Paintings and Books",
        ],
    },
    {
        "key": "hist7_our_pasts_2", "book": "Our Pasts II (Class 7)",
        "subject": "Medieval History", "grade": "Class 7",
        "read_url": "https://ncert.nic.in/textbook/pdf/gess1dd.zip",
        "chapters": [
            "Tracing Changes Through a Thousand Years",
            "New Kings and Kingdoms",
            "The Delhi Sultans",
            "The Mughal Empire",
            "Rulers and Buildings",
            "Towns, Traders and Craftspersons",
            "Tribes, Nomads and Settled Communities",
            "Devotional Paths to the Divine",
            "The Making of Regional Cultures",
            "Eighteenth-Century Political Formations",
        ],
    },
    {
        "key": "hist8_our_pasts_3", "book": "Our Pasts III (Class 8)",
        "subject": "Modern History", "grade": "Class 8",
        "read_url": "https://ncert.nic.in/textbook/pdf/hess2dd.zip",
        "chapters": [
            "How, When and Where",
            "From Trade to Territory",
            "Ruling the Countryside",
            "Tribals, Dikus and the Vision of a Golden Age",
            "When People Rebel: 1857 and After",
            "Colonialism and the City",
            "Weavers, Iron Smelters and Factory Owners",
            "Civilising the Native, Educating the Nation",
            "Women, Caste and Reform",
            "The Changing World of Visual Arts",
            "The Making of the National Movement: 1870s-1947",
            "India After Independence",
        ],
    },
    {
        "key": "hist9_contemporary_world_1", "book": "India and the Contemporary World I (Class 9)",
        "subject": "Modern History", "grade": "Class 9",
        "read_url": "archive:ncert-iess3",
        "chapters": [
            "The French Revolution",
            "Socialism in Europe and the Russian Revolution",
            "Nazism and the Rise of Hitler",
            "Forest Society and Colonialism",
            "Pastoralists in the Modern World",
        ],
    },
    {
        "key": "hist10_contemporary_world_2", "book": "India and the Contemporary World II (Class 10)",
        "subject": "Modern History", "grade": "Class 10",
        "read_url": "https://ncert.nic.in/textbook/pdf/jess3dd.zip",
        "chapters": [
            "The Rise of Nationalism in Europe",
            "Nationalism in India",
            "The Making of a Global World",
            "The Age of Industrialisation",
            "Print Culture and the Modern World",
        ],
    },
    {
        "key": "hist11_themes_world", "book": "Themes in World History (Class 11)",
        "subject": "World History", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/kehs1dd.zip",
        "chapters": [
            "From the Beginning of Time",
            "Writing and City Life",
            "An Empire Across Three Continents",
            "The Central Islamic Lands",
            "Nomadic Empires",
            "The Three Orders",
            "Changing Cultural Traditions",
            "Confrontation of Cultures",
            "The Industrial Revolution",
            "Displacing Indigenous Peoples",
            "Paths to Modernisation",
        ],
    },
    {
        "key": "hist12_themes_1", "book": "Themes in Indian History I (Class 12)",
        "subject": "Ancient History", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/lehs1dd.zip",
        "chapters": [
            "Bricks, Beads and Bones (The Harappan Civilisation)",
            "Kings, Farmers and Towns (Early States and Economies)",
            "Kinship, Caste and Class (Early Societies)",
            "Thinkers, Beliefs and Buildings (Cultural Developments)",
        ],
    },
    {
        "key": "hist12_themes_2", "book": "Themes in Indian History II (Class 12)",
        "subject": "Medieval History", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/lehs2dd.zip",
        "chapters": [
            "Through the Eyes of Travellers (Perceptions of Society)",
            "Bhakti-Sufi Traditions",
            "An Imperial Capital: Vijayanagara",
            "Peasants, Zamindars and the State (Agrarian Society and the Mughal Empire)",
            "Kings and Chronicles (The Mughal Courts)",
        ],
    },
    {
        "key": "hist12_themes_3", "book": "Themes in Indian History III (Class 12)",
        "subject": "Modern History", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/lehs3dd.zip",
        "chapters": [
            "Colonialism and the Countryside",
            "Rebels and the Raj (The Revolt of 1857)",
            "Colonial Cities",
            "Mahatma Gandhi and the Nationalist Movement",
            "Understanding Partition",
            "Framing the Constitution",
        ],
    },
    {
        "key": "hist_old_ancient", "book": "Ancient India (Old NCERT - R.S. Sharma)",
        "subject": "Ancient History", "grade": "Old NCERT",
        "read_url": "",
        "chapters": [
            "The Importance of Ancient Indian History",
            "The Construction of Ancient Indian History",
            "The Geographical Setting",
            "The Stone Age",
            "The Stone-Copper Phase",
            "The Harappan Civilization",
            "Advent of the Aryans and the Age of the Rig Veda",
            "The Later Vedic Phase: Transition to State and Social Formation",
            "Jainism and Buddhism",
            "Territorial States and the First Magadhan Empire",
            "Iranian and Macedonian Invasions",
            "State and Varna Society in the Age of the Buddha",
            "The Age of the Mauryas",
            "Significance of the Maurya Rule",
            "Central Asian Contacts and Their Results",
            "The Age of the Satavahanas",
            "The Dawn of History in the Deep South",
            "Crafts, Trade and Towns in the Post-Maurya Age",
            "The Rise and Growth of the Gupta Empire",
            "Life in the Gupta Age",
            "Spread of Civilization in Eastern India",
            "Harsha and His Times",
            "Formation of New States and Rural Expansion in the Peninsula",
            "India's Cultural Contacts with the Asian Countries",
            "Transformation of the Ancient Phase",
            "Sequence of Social Changes",
            "Legacy in Science and Civilization",
        ],
    },
    {
        "key": "hist_old_medieval", "book": "Medieval India (Old NCERT - Satish Chandra)",
        "subject": "Medieval History", "grade": "Old NCERT",
        "read_url": "",
        "chapters": [
            "India and the World",
            "Northern India: Age of the Three Empires (800-1000)",
            "South India: The Chola Empire (900-1200)",
            "Economic and Social Life, Education and Religious Belief (800-1200)",
            "Age of Conflict (Circa 1000-1200)",
            "The Delhi Sultanat - I (Circa 1200-1400)",
            "The Delhi Sultanat - II (Circa 1300-1400)",
            "Government, and Economic and Social Life during the Sultanate",
            "The Age of Vijayanagara and the Bahmanids, and the Coming of the Portuguese (Circa 1350-1565)",
            "Struggle for Empire in North India - I (1400-1525)",
            "Cultural Development in India (1200-1500)",
            "Struggle for Empire in North India - II: Mughals and Afghans (1525-1555)",
            "Consolidation of the Mughal Empire: Age of Akbar",
            "The Deccan and the South (Up to 1656)",
            "India in the First Half of the 17th Century",
            "Economic and Social Life under the Mughals",
            "Cultural and Religious Developments",
            "Climax and Disintegration of the Mughal Empire - I",
            "Climax and Disintegration of the Mughal Empire - II",
            "Assessment and Review of Medieval India",
        ],
    },
    {
        "key": "hist_old_modern", "book": "Modern India (Old NCERT - Bipan Chandra)",
        "subject": "Modern History", "grade": "Old NCERT",
        "read_url": "",
        "chapters": [
            "The Decline of the Mughal Empire",
            "Indian States and Society in the 18th Century",
            "The Beginnings of European Settlements",
            "The British Conquest of India",
            "The Structure of the Government and the Economic Policies of the British Empire in India, 1757-1857",
            "Administrative Organisation and Social and Cultural Policy",
            "Social and Cultural Awakening in the First Half of the 19th Century",
            "The Revolt of 1857",
            "Administrative Changes After 1858",
            "India and Her Neighbours",
            "Economic Impact of the British Rule",
            "Growth of New India - The Nationalist Movement 1858-1905",
            "Growth of New India - Religious and Social Reform After 1858",
            "Nationalist Movement 1905-1918",
            "Struggle for Swaraj",
        ],
    },
    {
        "key": "art11_indian_art", "book": "An Introduction to Indian Art (Class 11)",
        "subject": "Art & Culture", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/kefa1dd.zip",
        "chapters": [
            "Prehistoric Rock Paintings",
            "Arts of the Indus Valley",
            "Arts of the Mauryan Period",
            "Post-Mauryan Trends in Indian Art and Architecture",
            "Later Mural Traditions",
            "Temple Architecture and Sculpture",
            "Indian Bronze Sculpture",
            "Some Aspects of Indo-Islamic Architecture",
        ],
    },
    {
        "key": "art12_living_craft", "book": "Living Craft Traditions of India (Class 12)",
        "subject": "Art & Culture", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/khec1dd.zip",
        "chapters": [
            "Crafts Heritage",
            "Clay",
            "Stone",
            "Metal",
            "Jewellery",
            "Natural Fibres",
            "Paper Crafts",
            "Textiles",
            "Painting",
            "Theatre Crafts",
        ],
    },
    {
        "key": "pol9_democratic_politics_1", "book": "Democratic Politics I (Class 9)",
        "subject": "Indian Polity", "grade": "Class 9",
        "read_url": "archive:ncert-iess4",
        "chapters": [
            "What is Democracy? Why Democracy?",
            "Constitutional Design",
            "Electoral Politics",
            "Working of Institutions",
            "Democratic Rights",
        ],
    },
    {
        "key": "pol10_democratic_politics_2", "book": "Democratic Politics II (Class 10)",
        "subject": "Indian Polity", "grade": "Class 10",
        "read_url": "https://ncert.nic.in/textbook/pdf/jess4dd.zip",
        "chapters": [
            "Power Sharing",
            "Federalism",
            "Gender, Religion and Caste",
            "Political Parties",
            "Outcomes of Democracy",
        ],
    },
    {
        "key": "pol11_constitution_at_work", "book": "Indian Constitution at Work (Class 11)",
        "subject": "Indian Polity", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/keps2dd.zip",
        "chapters": [
            "Constitution: Why and How?",
            "Rights in the Indian Constitution",
            "Election and Representation",
            "Executive",
            "Legislature",
            "Judiciary",
            "Federalism",
            "Local Governments",
            "Constitution as a Living Document",
            "The Philosophy of the Constitution",
        ],
    },
    {
        "key": "pol11_political_theory", "book": "Political Theory (Class 11)",
        "subject": "Indian Polity", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/keps1dd.zip",
        "chapters": [
            "Political Theory: An Introduction",
            "Freedom",
            "Equality",
            "Social Justice",
            "Rights",
            "Citizenship",
            "Nationalism",
            "Secularism",
            "Peace",
            "Development",
        ],
    },
    {
        "key": "pol12_contemporary_world_politics", "book": "Contemporary World Politics (Class 12)",
        "subject": "International Relations", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/leps1dd.zip",
        "chapters": [
            "The Cold War Era",
            "The End of Bipolarity",
            "US Hegemony in World Politics",
            "Alternative Centres of Power",
            "Contemporary South Asia",
            "International Organisations",
            "Security in the Contemporary World",
            "Environment and Natural Resources",
            "Globalisation",
        ],
    },
    {
        "key": "pol12_politics_since_independence", "book": "Politics in India Since Independence (Class 12)",
        "subject": "Indian Polity", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/leps2dd.zip",
        "chapters": [
            "Challenges of Nation Building",
            "Era of One-Party Dominance",
            "Politics of Planned Development",
            "India's External Relations",
            "Challenges to and Restoration of the Congress System",
            "The Crisis of Democratic Order",
            "Rise of Popular Movements",
            "Regional Aspirations",
            "Recent Developments in Indian Politics",
        ],
    },
    {
        "key": "geo6_earth_habitat", "book": "The Earth: Our Habitat (Class 6)",
        "subject": "Geography", "grade": "Class 6",
        "read_url": "archive:ncert-fess2",
        "chapters": [
            "The Earth in the Solar System",
            "Globe: Latitudes and Longitudes",
            "Motions of the Earth",
            "Maps",
            "Major Domains of the Earth",
            "Major Landforms of the Earth",
            "Our Country - India",
            "India: Climate, Vegetation and Wildlife",
        ],
    },
    {
        "key": "geo7_our_environment", "book": "Our Environment (Class 7)",
        "subject": "Geography", "grade": "Class 7",
        "read_url": "https://ncert.nic.in/textbook/pdf/gess2dd.zip",
        "chapters": [
            "Environment",
            "Inside Our Earth",
            "Our Changing Earth",
            "Air",
            "Water",
            "Natural Vegetation and Wildlife",
            "Human Environment - Settlement, Transport and Communication",
            "Human-Environment Interactions: The Tropical and Subtropical Region",
            "Life in the Temperate Grasslands",
            "Life in the Deserts",
        ],
    },
    {
        "key": "geo8_resources_development", "book": "Resources and Development (Class 8)",
        "subject": "Geography", "grade": "Class 8",
        "read_url": "https://ncert.nic.in/textbook/pdf/hess4dd.zip",
        "chapters": [
            "Resources",
            "Land, Soil, Water, Natural Vegetation and Wildlife Resources",
            "Mineral and Power Resources",
            "Agriculture",
            "Industries",
            "Human Resources",
        ],
    },
    {
        "key": "geo9_contemporary_india_1", "book": "Contemporary India I (Class 9)",
        "subject": "Geography", "grade": "Class 9",
        "read_url": "archive:ncert-iess1",
        "chapters": [
            "India - Size and Location",
            "Physical Features of India",
            "Drainage",
            "Climate",
            "Natural Vegetation and Wildlife",
            "Population",
        ],
    },
    {
        "key": "geo10_contemporary_india_2", "book": "Contemporary India II (Class 10)",
        "subject": "Geography", "grade": "Class 10",
        "read_url": "https://ncert.nic.in/textbook/pdf/jess1dd.zip",
        "chapters": [
            "Resources and Development",
            "Forest and Wildlife Resources",
            "Water Resources",
            "Agriculture",
            "Minerals and Energy Resources",
            "Manufacturing Industries",
            "Lifelines of National Economy",
        ],
    },
    {
        "key": "geo11_physical", "book": "Fundamentals of Physical Geography (Class 11)",
        "subject": "Geography", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/kegy2dd.zip",
        "chapters": [
            "Geography as a Discipline",
            "The Origin and Evolution of the Earth",
            "Interior of the Earth",
            "Distribution of Oceans and Continents",
            "Minerals and Rocks",
            "Geomorphic Processes",
            "Landforms and their Evolution",
            "Composition and Structure of Atmosphere",
            "Solar Radiation, Heat Balance and Temperature",
            "Atmospheric Circulation and Weather Systems",
            "Water in the Atmosphere",
            "World Climate and Climate Change",
            "Water (Oceans)",
            "Movements of Ocean Water",
            "Life on the Earth",
            "Biodiversity and Conservation",
        ],
    },
    {
        "key": "geo11_india_physical", "book": "India: Physical Environment (Class 11)",
        "subject": "Geography", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/kegy1dd.zip",
        "chapters": [
            "India - Location",
            "Structure and Physiography",
            "Drainage System",
            "Climate",
            "Natural Vegetation",
            "Soils",
            "Natural Hazards and Disasters",
        ],
    },
    {
        "key": "geo12_human", "book": "Fundamentals of Human Geography (Class 12)",
        "subject": "Geography", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/legy1dd.zip",
        "chapters": [
            "Human Geography: Nature and Scope",
            "The World Population: Distribution, Density and Growth",
            "Population Composition",
            "Human Development",
            "Primary Activities",
            "Secondary Activities",
            "Tertiary and Quaternary Activities",
            "Transport and Communication",
            "International Trade",
            "Human Settlements",
        ],
    },
    {
        "key": "geo12_india_people_economy", "book": "India: People and Economy (Class 12)",
        "subject": "Geography", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/legy2dd.zip",
        "chapters": [
            "Population: Distribution, Density, Growth and Composition",
            "Migration: Types, Causes and Consequences",
            "Human Development",
            "Human Settlements",
            "Land Resources and Agriculture",
            "Water Resources",
            "Mineral and Energy Resources",
            "Manufacturing Industries",
            "Planning and Sustainable Development in Indian Context",
            "Transport and Communication",
            "International Trade",
            "Geographical Perspective on Selected Issues and Problems",
        ],
    },
    {
        "key": "eco9_economics", "book": "Economics (Class 9)",
        "subject": "Indian Economy", "grade": "Class 9",
        "read_url": "archive:ncert-iess2",
        "chapters": [
            "The Story of Village Palampur",
            "People as Resource",
            "Poverty as a Challenge",
            "Food Security in India",
        ],
    },
    {
        "key": "eco10_understanding_dev", "book": "Understanding Economic Development (Class 10)",
        "subject": "Indian Economy", "grade": "Class 10",
        "read_url": "https://ncert.nic.in/textbook/pdf/jess2dd.zip",
        "chapters": [
            "Development",
            "Sectors of the Indian Economy",
            "Money and Credit",
            "Globalisation and the Indian Economy",
            "Consumer Rights",
        ],
    },
    {
        "key": "eco11_indian_dev", "book": "Indian Economic Development (Class 11)",
        "subject": "Indian Economy", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/keec1dd.zip",
        "chapters": [
            "Indian Economy on the Eve of Independence",
            "Indian Economy 1950-1990",
            "Liberalisation, Privatisation and Globalisation: An Appraisal",
            "Poverty",
            "Human Capital Formation in India",
            "Rural Development",
            "Employment: Growth, Informalisation and Other Issues",
            "Infrastructure",
            "Environment and Sustainable Development",
            "Comparative Development Experiences of India and its Neighbours",
        ],
    },
    {
        "key": "eco12_micro", "book": "Introductory Microeconomics (Class 12)",
        "subject": "Indian Economy", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/leec1dd.zip",
        "chapters": [
            "Introduction to Microeconomics",
            "Theory of Consumer Behaviour",
            "Production and Costs",
            "The Theory of the Firm under Perfect Competition",
            "Market Equilibrium",
            "Non-competitive Markets",
        ],
    },
    {
        "key": "eco12_macro", "book": "Introductory Macroeconomics (Class 12)",
        "subject": "Indian Economy", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/leec2dd.zip",
        "chapters": [
            "Introduction to Macroeconomics",
            "National Income Accounting",
            "Money and Banking",
            "Determination of Income and Employment",
            "Government Budget and the Economy",
            "Open Economy Macroeconomics",
        ],
    },
    {
        "key": "sci8_science", "book": "Science (Class 8)",
        "subject": "Science & Technology", "grade": "Class 8",
        "read_url": "https://ncert.nic.in/textbook/pdf/hesc1dd.zip",
        "chapters": [
            "Crop Production and Management",
            "Microorganisms: Friend and Foe",
            "Synthetic Fibres and Plastics",
            "Materials: Metals and Non-Metals",
            "Coal and Petroleum",
            "Combustion and Flame",
            "Conservation of Plants and Animals",
            "Cell Structure and Functions",
            "Reproduction in Animals",
            "Reaching the Age of Adolescence",
            "Force and Pressure",
            "Friction",
            "Sound",
            "Chemical Effects of Electric Current",
            "Some Natural Phenomena",
            "Light",
            "Stars and the Solar System",
            "Pollution of Air and Water",
        ],
    },
    {
        "key": "sci9_science", "book": "Science (Class 9)",
        "subject": "Science & Technology", "grade": "Class 9",
        "read_url": "https://ncert.nic.in/textbook/pdf/iesc1dd.zip",
        "chapters": [
            "Matter in Our Surroundings",
            "Is Matter Around Us Pure?",
            "Atoms and Molecules",
            "Structure of the Atom",
            "The Fundamental Unit of Life",
            "Tissues",
            "Diversity in Living Organisms",
            "Motion",
            "Force and Laws of Motion",
            "Gravitation",
            "Work and Energy",
            "Sound",
            "Why Do We Fall Ill?",
            "Natural Resources",
            "Improvement in Food Resources",
        ],
    },
    {
        "key": "sci10_science", "book": "Science (Class 10)",
        "subject": "Science & Technology", "grade": "Class 10",
        "read_url": "https://ncert.nic.in/textbook/pdf/jesc1dd.zip",
        "chapters": [
            "Chemical Reactions and Equations",
            "Acids, Bases and Salts",
            "Metals and Non-metals",
            "Carbon and its Compounds",
            "Periodic Classification of Elements",
            "Life Processes",
            "Control and Coordination",
            "How do Organisms Reproduce?",
            "Heredity and Evolution",
            "Light - Reflection and Refraction",
            "The Human Eye and the Colourful World",
            "Electricity",
            "Magnetic Effects of Electric Current",
            "Sources of Energy",
            "Our Environment",
            "Management of Natural Resources",
        ],
    },
    {
        "key": "sci_senior_chemistry", "book": "Chemistry (Class 11 & 12) - UPSC-relevant chapters",
        "subject": "Science & Technology", "grade": "Class 11-12",
        "read_url": "https://ncert.nic.in/textbook/pdf/kech1dd.zip",
        "chapters": [
            "Environmental Chemistry (Class 11, Unit 14)",
            "Chemistry in Everyday Life (Class 12, Unit 16)",
        ],
    },
    {
        "key": "sci_senior_biology", "book": "Biology (Class 11 & 12) - UPSC-relevant chapters",
        "subject": "Science & Technology", "grade": "Class 11-12",
        "read_url": "https://ncert.nic.in/textbook/pdf/kebo1dd.zip",
        "chapters": [
            "Biological Classification (Class 11)",
            "Plant Physiology (Class 11, Unit 4)",
            "Human Physiology (Class 11, Unit 5)",
            "Biotechnology: Principles and Processes (Class 12)",
            "Biotechnology and its Applications (Class 12)",
            "Human Health and Disease (Class 12)",
            "Microbes in Human Welfare (Class 12)",
        ],
    },
    {
        "key": "env12_biology_ecology", "book": "Biology (Class 12) - Ecology & Environment",
        "subject": "Environment & Ecology", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/lebo1dd.zip",
        "chapters": [
            "Organisms and Populations",
            "Ecosystem",
            "Biodiversity and Conservation",
            "Environmental Issues",
        ],
    },
    {
        "key": "soc6_social_political_1", "book": "Social and Political Life I (Class 6)",
        "subject": "Indian Society", "grade": "Class 6",
        "read_url": "archive:ncert-fess3",
        "chapters": [
            "Understanding Diversity",
            "Diversity and Discrimination",
            "What is Government",
            "Key Elements of a Democratic Government",
            "Panchayati Raj",
            "Rural Administration",
            "Urban Administration",
            "Rural Livelihoods",
            "Urban Livelihoods",
        ],
    },
    {
        "key": "soc7_social_political_2", "book": "Social and Political Life II (Class 7)",
        "subject": "Indian Society", "grade": "Class 7",
        "read_url": "https://ncert.nic.in/textbook/pdf/gess3dd.zip",
        "chapters": [
            "On Equality",
            "Role of the Government in Health",
            "How the State Government Works",
            "Growing up as Boys and Girls",
            "Women Change the World",
            "Understanding Media",
            "Markets Around Us",
            "A Shirt in the Market",
            "Struggles for Equality",
        ],
    },
    {
        "key": "soc8_social_political_3", "book": "Social and Political Life III (Class 8)",
        "subject": "Indian Society", "grade": "Class 8",
        "read_url": "https://ncert.nic.in/textbook/pdf/hess3dd.zip",
        "chapters": [
            "The Indian Constitution",
            "Understanding Secularism",
            "Why Do We Need a Parliament?",
            "Understanding Laws",
            "Judiciary",
            "Understanding Our Criminal Justice System",
            "Understanding Marginalisation",
            "Confronting Marginalisation",
            "Public Facilities",
            "Law and Social Justice",
        ],
    },
    {
        "key": "soc11_understanding_society", "book": "Sociology: Understanding Society (Class 11)",
        "subject": "Indian Society", "grade": "Class 11",
        "read_url": "https://ncert.nic.in/textbook/pdf/kesy2dd.zip",
        "chapters": [
            "Sociology and Society",
            "Terms, Concepts and their Use in Sociology",
            "Understanding Social Institutions",
            "Culture and Socialisation",
            "Doing Sociology: Research Methods",
            "Social Structure, Stratification and Social Processes in Society",
            "Social Change and Social Order in Rural and Urban Society",
            "Environment and Society",
            "Introducing Western Sociologists",
            "Indian Sociologists",
        ],
    },
    {
        "key": "soc12_indian_society", "book": "Indian Society (Class 12)",
        "subject": "Indian Society", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/lesy1dd.zip",
        "chapters": [
            "Introducing Indian Society",
            "The Demographic Structure of the Indian Society",
            "Social Institutions: Continuity and Change",
            "The Market as a Social Institution",
            "Patterns of Social Inequality and Exclusion",
            "The Challenges of Cultural Diversity",
        ],
    },
    {
        "key": "soc12_social_change", "book": "Social Change and Development in India (Class 12)",
        "subject": "Indian Society", "grade": "Class 12",
        "read_url": "https://ncert.nic.in/textbook/pdf/lesy2dd.zip",
        "chapters": [
            "Structural Change",
            "Cultural Change",
            "The Story of Indian Democracy",
            "Change and Development in Rural Society",
            "Change and Development in Industrial Society",
            "Globalisation and Social Change",
            "Mass Media and Communications",
            "Social Movements",
        ],
    },
]

# ── Reference books -> subject -> high-yield topics ────────────────────────────
# Standard UPSC reference books (toppers' booklist). Used both for the Bookwise
# practice tab and to ground AI generation in a recognised source.
REFERENCE_BOOKS = [
    # ---------------- ANCIENT HISTORY ----------------
    {"book": "India's Ancient Past - R.S. Sharma", "subject": "Ancient History", "topics": [
        "Stone Age and Prehistory", "Indus Valley Civilisation", "Vedic Age",
        "Jainism and Buddhism", "Mahajanapadas and Magadha", "Mauryan Empire",
        "Post-Mauryan Period", "Gupta Empire", "Sangam Age and South India",
        "Art, Architecture, Society and Economy"]},
    {"book": "History of Ancient and Early Medieval India - Upinder Singh", "subject": "Ancient History", "topics": [
        "Prehistoric Cultures", "Harappan Civilisation", "Vedic Period",
        "Early States and Mahajanapadas", "Mauryan Empire", "Post-Mauryan States",
        "Gupta and Post-Gupta Period", "Early Medieval India", "Art and Culture"]},
    {"book": "The Wonder That Was India - A.L. Basham", "subject": "Ancient History", "topics": [
        "Indus Civilisation", "Vedic Religion and Society", "Buddhism and Jainism",
        "Mauryan and Gupta Ages", "Caste and Society", "Art and Architecture",
        "Philosophy, Language and Literature"]},
    {"book": "Ancient History of India - Snehil Tripathi & Sonali Bansal", "subject": "Ancient History", "topics": [
        "Prehistoric Period", "Indus Valley Civilisation", "Vedic Culture",
        "Religious Movements", "Mauryan and Gupta Empires", "South Indian Kingdoms",
        "Art and Culture"]},

    # ---------------- MEDIEVAL HISTORY ----------------
    {"book": "History of Medieval India - Satish Chandra", "subject": "Medieval History", "topics": [
        "Early Medieval India", "Delhi Sultanate", "Vijayanagara and Bahmani Kingdoms",
        "Bhakti and Sufi Movements", "Mughal Empire", "Maratha Empire",
        "Administration and Economy", "Art and Architecture"]},
    {"book": "The Wonder That Was India Vol. II - S.A.A. Rizvi", "subject": "Medieval History", "topics": [
        "Delhi Sultanate", "Mughal Empire", "Religion (Bhakti and Sufi)",
        "Society and Economy", "Art, Architecture and Culture"]},

    # ---------------- MODERN HISTORY ----------------
    {"book": "Spectrum - A Brief History of Modern India", "subject": "Modern History", "topics": [
        "Advent of Europeans", "British Expansion in India", "Economic Impact of British Rule",
        "Revolt of 1857", "Socio-Religious Reform Movements", "Rise of Indian Nationalism",
        "Moderate and Extremist Phase", "Partition of Bengal and Swadeshi Movement",
        "Home Rule Movement", "Gandhian Movements (Non-Cooperation, Civil Disobedience, Quit India)",
        "Revolutionary Movements", "Towards Independence and Partition", "Governor-Generals and Viceroys"]},
    {"book": "History of Modern India - Bipan Chandra", "subject": "Modern History", "topics": [
        "British Conquest of India", "Economic Impact of Colonial Rule",
        "Administrative Changes", "Revolt of 1857", "Socio-Religious Reforms",
        "Rise of Nationalism", "Freedom Struggle", "Towards Independence"]},
    {"book": "India's Struggle for Independence - Bipan Chandra", "subject": "Modern History", "topics": [
        "Revolt of 1857", "Early Nationalism", "Moderates and Extremists",
        "Swadeshi Movement", "Gandhian Mass Movements", "Revolutionary Activities",
        "Quit India Movement", "Partition and Independence"]},

    # ---------------- POST-INDEPENDENCE INDIA ----------------
    {"book": "India After Gandhi - Ramachandra Guha", "subject": "Post-Independence India", "topics": [
        "Nation Building and Integration", "Linguistic Reorganisation of States",
        "Nehruvian Era", "Wars and Foreign Policy", "The Emergency",
        "Economic Liberalisation", "Coalition Politics and Recent Developments"]},
    {"book": "India Since Independence - Bipan Chandra", "subject": "Post-Independence India", "topics": [
        "Challenges of Nation Building", "Consolidation of Democracy",
        "Planned Economic Development", "Foreign Policy", "Punjab and Regional Movements",
        "Politics since the 1990s"]},

    # ---------------- ART & CULTURE ----------------
    {"book": "Nitin Singhania - Indian Art and Culture", "subject": "Art & Culture", "topics": [
        "Indian Architecture (Temple, Cave, Stupa)", "Indo-Islamic and Colonial Architecture",
        "Indian Paintings", "Indian Music", "Classical Dance Forms", "Theatre and Puppetry",
        "Indian Literature", "Religion and Philosophy", "Bhakti and Sufi Movements",
        "UNESCO Heritage Sites", "Fairs, Festivals and Martial Arts"]},
    {"book": "Indian Art, Heritage and Culture - Pushpesh Pant", "subject": "Art & Culture", "topics": [
        "Architecture and Sculpture", "Paintings", "Performing Arts (Music, Dance, Theatre)",
        "Literature and Languages", "Religion and Philosophy", "Cultural Institutions and Heritage"]},
    {"book": "CCRT - Indian Culture", "subject": "Art & Culture", "topics": [
        "Visual Arts", "Performing Arts", "Architecture", "Literary Heritage",
        "Cultural Traditions", "Fairs and Festivals"]},

    # ---------------- GEOGRAPHY ----------------
    {"book": "GC Leong - Certificate Physical and Human Geography", "subject": "Geography", "topics": [
        "The Earth and the Universe", "Earth's Interior and Plate Tectonics",
        "Landforms (Volcanoes, Earthquakes, Folding, Faulting)", "Weathering and Erosion",
        "Atmosphere and Insolation", "Pressure Belts and Winds", "Humidity and Precipitation",
        "Climatic Regions of the World", "Oceans (Currents, Tides, Salinity)",
        "Natural Vegetation and Soils"]},
    {"book": "World Geography - Majid Husain", "subject": "Geography", "topics": [
        "The Universe and Solar System", "Geomorphology", "Climatology",
        "Oceanography", "Biogeography", "Economic Geography", "World Regional Geography"]},
    {"book": "Physical Geography - Savindra Singh", "subject": "Geography", "topics": [
        "Geomorphology", "Climatology", "Oceanography", "Soil Geography", "Biogeography"]},
    {"book": "Human Geography - Majid Husain", "subject": "Geography", "topics": [
        "Population and Migration", "Human Settlements", "Economic Activities",
        "Resources", "Transport and Communication", "International Trade"]},

    # ---------------- INDIAN POLITY ----------------
    {"book": "Laxmikanth - Indian Polity", "subject": "Indian Polity", "topics": [
        "Historical Background", "Making of the Constitution", "Salient Features", "Preamble",
        "Union and its Territory", "Citizenship", "Fundamental Rights",
        "Directive Principles of State Policy", "Fundamental Duties",
        "Amendment of the Constitution", "Basic Structure Doctrine", "Parliamentary System",
        "Federal System", "Centre-State Relations", "Emergency Provisions", "President",
        "Prime Minister and Council of Ministers", "Parliament", "Supreme Court", "High Courts",
        "Governor", "Panchayati Raj", "Municipalities", "Election Commission",
        "Constitutional and Non-Constitutional Bodies"]},
    {"book": "Introduction to the Constitution of India - D.D. Basu", "subject": "Indian Polity", "topics": [
        "Making of the Constitution", "Preamble and Salient Features", "Fundamental Rights",
        "Directive Principles and Duties", "Union and State Executive", "Parliament and Legislature",
        "Judiciary", "Centre-State Relations", "Amendment Process", "Emergency Provisions"]},

    # ---------------- INDIAN ECONOMY ----------------
    {"book": "Ramesh Singh - Indian Economy", "subject": "Indian Economy", "topics": [
        "National Income", "Economic Growth and Development", "Planning in India",
        "Money and Banking", "Monetary Policy and RBI", "Fiscal Policy and Budget",
        "Inflation", "Taxation and GST", "Financial Markets", "Banking Sector Reforms",
        "External Sector and Balance of Payments", "Foreign Trade Policy",
        "Poverty and Unemployment", "Agriculture", "Industry and Infrastructure"]},

    # ---------------- ENVIRONMENT & ECOLOGY ----------------
    {"book": "Shankar IAS - Environment", "subject": "Environment & Ecology", "topics": [
        "Ecology and Ecosystem", "Biodiversity", "Biodiversity Conservation",
        "Protected Areas and National Parks", "Climate Change", "Ozone Depletion",
        "Environmental Pollution", "Environmental Acts and Policies",
        "Environmental Organisations and Conventions", "Wildlife and Species in News",
        "Wetlands and Ramsar Sites", "Agriculture and Environment", "Renewable Energy"]},
    {"book": "Environmental Studies: From Crisis to Cure - R. Rajagopalan", "subject": "Environment & Ecology", "topics": [
        "Ecosystems", "Biodiversity", "Natural Resources", "Environmental Pollution",
        "Environmental Management", "Sustainable Development", "Environmental Laws"]},
    {"book": "Environment - Ravi P. Agrahari", "subject": "Environment & Ecology", "topics": [
        "Ecology and Ecosystems", "Biodiversity", "Climate Change", "Pollution",
        "Environmental Conventions", "Acts and Policies", "Wildlife Conservation"]},

    # ---------------- SCIENCE & TECHNOLOGY ----------------
    {"book": "Science and Technology - Sheelwant Singh", "subject": "Science & Technology", "topics": [
        "Space Technology", "Defence Technology", "Nuclear Technology", "Biotechnology",
        "Information Technology and Communications", "Nanotechnology",
        "Health, Diseases and Vaccines", "Energy and Robotics"]},

    # ---------------- WORLD HISTORY ----------------
    {"book": "Mastering Modern World History - Norman Lowe", "subject": "World History", "topics": [
        "World War I", "Russian Revolution", "Rise of Fascism and Nazism", "World War II",
        "The Cold War", "Decolonisation", "League of Nations and United Nations", "World Economy"]},
    {"book": "History of the World - Arjun Dev", "subject": "World History", "topics": [
        "Industrial Revolution", "Nationalism in Europe", "Imperialism and Colonialism",
        "World Wars", "Russian and Chinese Revolutions", "Decolonisation and the Third World"]},

    # ---------------- INDIAN SOCIETY ----------------
    {"book": "Social Problems in India - Ram Ahuja", "subject": "Indian Society", "topics": [
        "Population and Demography", "Caste and Class", "Gender and Women's Issues",
        "Communalism and Regionalism", "Poverty and Unemployment", "Urbanisation",
        "Social Change", "Social Movements"]},

    # ---------------- INTERNATIONAL RELATIONS ----------------
    {"book": "Pax Indica - Shashi Tharoor", "subject": "International Relations", "topics": [
        "India's Foreign Policy", "India and its Neighbours", "India and Major Powers",
        "Multilateral Institutions", "Diaspora and Soft Power"]},
    {"book": "International Relations: The India Way - S. Jaishankar", "subject": "International Relations", "topics": [
        "India's Strategic Outlook", "Bilateral Relations", "Global Governance",
        "Geopolitics and Geoeconomics", "Economic Diplomacy"]},

    # ---------------- INTERNAL SECURITY ----------------
    {"book": "Internal Security - M. Karthikeyan", "subject": "Internal Security & Disaster Management", "topics": [
        "Security Challenges", "Terrorism", "Left-Wing Extremism (Naxalism)", "Insurgency",
        "Cyber Security", "Border Management", "Security Forces and Agencies"]},
    {"book": "Internal Security and Disaster Management - Syed Waquar Raza", "subject": "Internal Security & Disaster Management", "topics": [
        "Internal Security Threats", "Money Laundering and Organised Crime",
        "Communication and Social Media", "Disaster Management", "Disaster Risk Reduction"]},

    # ---------------- CSAT (PAPER II) ----------------
    {"book": "Quantitative Aptitude - R.S. Aggarwal", "subject": "CSAT - Quantitative Aptitude", "topics": [
        "Number System", "Percentages", "Ratio and Proportion", "Averages",
        "Time and Work", "Time, Speed and Distance", "Profit and Loss",
        "Simple and Compound Interest", "Permutation, Combination and Probability",
        "Data Interpretation"]},
    {"book": "Analytical Reasoning - M.K. Pandey", "subject": "CSAT - Reasoning", "topics": [
        "Syllogism", "Seating Arrangement", "Blood Relations", "Coding-Decoding",
        "Puzzles", "Direction Sense", "Logical Deductions", "Statement and Assumptions"]},
    {"book": "Verbal & Non-Verbal Reasoning - R.S. Aggarwal", "subject": "CSAT - Reasoning", "topics": [
        "Series Completion", "Analogy", "Classification", "Coding-Decoding",
        "Logical Venn Diagrams", "Mirror and Water Images", "Non-Verbal Reasoning"]},

    # ---------------- GOVERNANCE ----------------
    {"book": "Governance (2nd ARC / NITI Aayog material)", "subject": "Governance", "topics": [
        "Citizen-Centric Administration", "e-Governance", "RTI and Transparency",
        "Civil Services Reforms", "Public Service Delivery", "Accountability and Ethics",
        "NITI Aayog Initiatives"]},

    # ---------------- ETHICS ----------------
    {"book": "Ethical Dilemmas of a Civil Servant - Anil Swarup", "subject": "Ethics", "topics": [
        "Ethics in Public Administration", "Integrity and Probity", "Conflicts of Interest",
        "Accountability", "Ethical Case Studies"]},

    # ---------------- ESSAY ----------------
    {"book": "Essays for Civil Services - Pulkit Khare", "subject": "Essay", "topics": [
        "Essay Structure and Approach", "Philosophical Themes", "Social Issues",
        "Polity and Economy Themes", "Quotes and Anecdotes"]},
]

# ── Subject -> high-yield topics (drives the Subjectwise practice tab) ─────────
SUBJECT_TOPICS = [
    {"subject": "Indian Polity", "topics": [
        "Historical Background and Making of the Constitution", "Salient Features and Preamble",
        "Union and its Territory", "Citizenship", "Fundamental Rights",
        "Directive Principles of State Policy", "Fundamental Duties",
        "Amendment of the Constitution and Basic Structure",
        "Parliamentary and Federal System", "Centre-State Relations", "Emergency Provisions",
        "President, Vice-President and Governor", "Prime Minister and Council of Ministers",
        "Parliament", "Supreme Court and Judiciary", "Panchayati Raj and Local Government",
        "Constitutional and Non-Constitutional Bodies", "Elections and Representation"]},
    {"subject": "Ancient History", "topics": [
        "Prehistoric Period", "Indus Valley Civilisation", "Vedic Age",
        "Jainism and Buddhism", "Mahajanapadas and Magadha", "Mauryan Empire",
        "Post-Mauryan Period", "Gupta Empire", "Sangam Age and South India",
        "Art, Architecture and Culture"]},
    {"subject": "Medieval History", "topics": [
        "Early Medieval India", "Delhi Sultanate", "Vijayanagara and Bahmani Kingdoms",
        "Bhakti and Sufi Movements", "Mughal Empire", "Maratha Empire",
        "Art and Architecture", "Regional Kingdoms"]},
    {"subject": "Modern History", "topics": [
        "Advent of Europeans", "British Expansion in India", "Economic Impact of British Rule",
        "Revolt of 1857", "Socio-Religious Reform Movements", "Rise of Indian Nationalism",
        "Moderate and Extremist Phase", "Swadeshi and Home Rule Movement",
        "Gandhian Movements (Non-Cooperation, Civil Disobedience, Quit India)",
        "Revolutionary Movements", "Towards Independence and Partition",
        "Governor-Generals and Viceroys"]},
    {"subject": "Post-Independence India", "topics": [
        "Nation Building and Integration of States", "Linguistic Reorganisation",
        "Nehruvian Era and Planning", "Wars and Foreign Policy", "The Emergency",
        "Economic Reforms of 1991", "Coalition Politics and Recent Developments"]},
    {"subject": "Art & Culture", "topics": [
        "Indian Architecture (Temple, Cave, Stupa)", "Indo-Islamic and Colonial Architecture",
        "Indian Paintings", "Indian Music", "Classical Dance Forms", "Theatre and Puppetry",
        "Indian Literature and Languages", "Religion and Philosophy",
        "Bhakti and Sufi Traditions", "UNESCO Heritage Sites", "Fairs, Festivals and Martial Arts"]},
    {"subject": "Geography", "topics": [
        "Geomorphology (Earth's Interior, Plate Tectonics, Landforms)",
        "Climatology (Atmosphere, Winds, Climate)", "Oceanography (Currents, Tides, Salinity)",
        "Indian Physiography and Drainage", "Indian Climate, Monsoon and Soils",
        "Natural Vegetation and Wildlife", "Indian Agriculture", "Mineral and Energy Resources",
        "Industries and Settlements", "World Geography and Regions", "Economic and Human Geography"]},
    {"subject": "Indian Economy", "topics": [
        "National Income and Economic Growth", "Planning and Economic Reforms",
        "Money, Banking and RBI", "Monetary and Fiscal Policy", "Inflation",
        "Budget and Taxation (GST)", "Financial Markets", "External Sector and BoP",
        "Poverty and Unemployment", "Agriculture and Food Security",
        "Industry and Infrastructure", "Inclusive Growth and Government Schemes"]},
    {"subject": "Environment & Ecology", "topics": [
        "Ecology and Ecosystems", "Biodiversity", "Biodiversity Conservation",
        "Protected Areas (National Parks, Sanctuaries, Reserves)", "Climate Change",
        "Ozone Depletion", "Environmental Pollution", "Environmental Laws and Policies",
        "International Conventions and Organisations", "Wetlands and Ramsar Sites",
        "Wildlife and Species in News", "Renewable Energy and Sustainability"]},
    {"subject": "Science & Technology", "topics": [
        "Physics in Everyday Life", "Chemistry in Everyday Life", "Human Physiology and Health",
        "Biotechnology", "Space Technology", "Defence Technology", "Nuclear Technology",
        "Information Technology and Computers", "Nanotechnology", "Diseases and Health Programmes"]},
    {"subject": "World History", "topics": [
        "Industrial Revolution", "American and French Revolutions", "Nationalism in Europe",
        "Imperialism and Colonialism", "World War I", "Russian Revolution",
        "Rise of Fascism and Nazism", "World War II", "The Cold War", "Decolonisation"]},
    {"subject": "Indian Society", "topics": [
        "Population and Demography", "Caste and Class", "Gender and Women's Issues",
        "Communalism, Regionalism and Secularism", "Poverty and Unemployment",
        "Urbanisation", "Social Empowerment", "Social Movements", "Globalisation and Society"]},
    {"subject": "International Relations", "topics": [
        "India's Foreign Policy", "India and its Neighbours", "India and Major Powers",
        "International and Regional Organisations", "Groupings and Agreements",
        "India's Diaspora and Soft Power", "Global Issues and Diplomacy"]},
    {"subject": "Internal Security & Disaster Management", "topics": [
        "Security Challenges and Terrorism", "Left-Wing Extremism", "Insurgency and Border Management",
        "Cyber Security", "Money Laundering and Organised Crime", "Security Forces and Agencies",
        "Disaster Management", "Disaster Risk Reduction"]},
    {"subject": "Governance", "topics": [
        "Citizen-Centric Administration", "e-Governance", "Transparency and RTI",
        "Civil Services and Administrative Reforms", "Public Service Delivery",
        "Role of Civil Society and NGOs", "Government Schemes and Policies"]},
    {"subject": "Ethics", "topics": [
        "Ethics and Human Interface", "Attitude and Aptitude", "Emotional Intelligence",
        "Probity in Governance", "Integrity and Accountability", "Ethical Case Studies"]},
    {"subject": "CSAT - Quantitative Aptitude", "topics": [
        "Number System", "Percentages", "Ratio and Proportion", "Averages",
        "Time and Work", "Time, Speed and Distance", "Profit and Loss",
        "Simple and Compound Interest", "Probability and Combinatorics", "Data Interpretation"]},
    {"subject": "CSAT - Reasoning", "topics": [
        "Syllogism", "Seating Arrangement", "Blood Relations", "Coding-Decoding",
        "Series and Analogy", "Direction Sense", "Puzzles", "Logical Deductions",
        "Statement and Assumptions"]},
]


def list_subjects():
    """Subjects with their topic lists for the Subjectwise practice tab."""
    return SUBJECT_TOPICS


def list_ncert_books():
    """Lightweight list for the API/frontend (no chapter bodies)."""
    return [
        {
            "key": b["key"], "book": b["book"], "subject": b["subject"],
            "grade": b["grade"], "chapter_count": len(b["chapters"]),
        }
        for b in NCERT_BOOKS
    ]


def get_ncert_book(key: str):
    """Full book dict (with chapters) by key, or None."""
    for b in NCERT_BOOKS:
        if b["key"] == key:
            return b
    return None
