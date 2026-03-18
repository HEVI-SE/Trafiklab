"""Configuration constants for the Stockholm bus deadhead analysis tool."""

import os

# API
API_KEY_KODA = os.environ.get("KODA_API_KEY", "4psdkvdO9UIYsziDkp3AlnGUL5N5a4tE19N2TSja28I")
OPERATOR = "sl"

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Deadhead detection thresholds
MIN_DEADHEAD_MOVE_METERS = 500       # Minimum movement to count as deadhead
MAX_DEADHEAD_SPEED_KMH = 90          # Max realistic speed for a bus (km/h)
MIN_DEADHEAD_SPEED_KMH = 2           # Min speed - slower is likely parked, not moving
MAX_DEADHEAD_DURATION_MIN = 180      # Max duration for a single deadhead (3 hours)
MIN_DEADHEAD_DURATION_MIN = 1        # Min duration - shorter is likely GPS noise

# Bus route types (standard + extended GTFS)
# Standard: 3 = Bus.  Extended: 700 = Bus, 702 = Express, 704 = Local, etc.
BUS_ROUTE_TYPES = {"3", "700", "702", "704", "712", "713", "714", "715", "717"}

# Label constants
NO_TRIP_LABEL = "Okänd tur"
NO_TRIP_COLOR = "#5f6368"

# Operator mapping for known SL bus routes in Stockholm County.
#
# Contract areas (avtalsområden) as of 2025:
#   Keolis   – Innerstad+Lidingö (E46), Bromma/Solna/Sundbyberg/Sollentuna (E42)
#   Nobina   – Huddinge/Botkyrka/Söderort (E40), Nacka/Värmdö (E41),
#              Handen/Nynäshamn (E44, from mid-2025)
#   Nobina   – Järfälla/Upplands-Bro (E43, VR takes over Aug 2026),
#              Södertälje/Nykvarn (E39, VR takes over Aug 2026)
#   Transdev – Norrort: Täby/Danderyd/Vaxholm/Österåker/Vallentuna (E35),
#              Norrtälje (E38), Sigtuna/Upplands Väsby/Märsta (E36)
#   VR       – Ekerö (E32), Tyresö (E45, from Aug 2025),
#              Järfälla/Upplands-Bro & Södertälje/Nykvarn (from Aug 2026)
#
# Sources:
#   Region Stockholm press releases 2023–2025
#   Bussmagasinet.se, Nobina.se, Transdev.se, Keolis.se
#   Wikipedia: Busstrafik i Stockholms län

def _expand(operator, routes):
    """Helper to build mapping entries from a list of route names."""
    return [{"route_short_name": str(r), "operator": operator} for r in routes]

# --- Keolis: Innerstaden & Lidingö (avtalsområde E46) ---
# Stombuss (blåbuss) 1-6, plus inner-city lines 0-99 range and Lidingö 200-series
_KEOLIS_INNERSTAD = [
    1, 2, 3, 4, 5, 6,                             # Stombusslinjer
    "2X",
    40, 41, 42, 43, "43X", 44, 45, 46, 47, 48, 49,
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
    61, 65, 66, 67, 69,
    71, 72, 73, 74, 76, 77, 78, 79,
    80, 82, 84, 85, 86, 87, 88, 89,
    90, 91, 92, 93, 94, 96,
]
_KEOLIS_LIDINGO = [
    201, 202, 203, 204, 205, 206, 207, 211, 212, 221, 222, 225, 233,
]

# --- Keolis: Bromma, Solna, Sundbyberg, Sollentuna (avtalsområde E42) ---
# 54 lines, ~130k daily boardings. Active since Aug 2024.
_KEOLIS_BROMMA_SOLNA = [
    101, 113, 116, 117, 118, 119, 122,
    501, 503, 504, "505", "505X", 506, 507, 508, 509,
    510, 511, 512, 513, 514, 515, 516, 519,
    520, "520X", 522, 523, 525, 526, 527, 528,
    540, 592, 595, 598,
]

# --- Nobina: Huddinge / Botkyrka / Söderort (avtalsområde E40, from Jan 2025) ---
_NOBINA_HBS = [
    131, 132, 133, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149,
    150, 151, 154, 155, 156, 157, 158, 159,
    160, 161, 162, 163, 164, 165, 166, 167, 168, 169,
    170, 171, 172, 173, 174, 176, 177, 178, 179,
    707, 708, 709, 710, 712, 713, 714, 715,
    "715H", "715V", 716, 717, 718, 719,
    720, 721, 722, 723, 724, 725, 726, 727, 728, 729,
    731, 732, 733, 734, 735, 736, 737, 738, 739,
    740, "740X", 741, 742, 743, 744, 745, 746, 747,
    791, 795, 796,
]

# --- Nobina: Nacka / Värmdö (avtalsområde E41, from Feb 2025) ---
_NOBINA_NV = [
    "71T",
    401, 402, 403, 404, 405, 406, 407, 408, 409,
    410, 411, 412, 413, 414, 415, 416, 417, 418, 419,
    420, 421, 422, 423, 424, 425, 426, 427, 428, 429,
    430, 431, 432, 433, 434, 435,
    440, 441, 442, 443, 444, 445, 446, 447, 448, 449,
    451, 452, 453, 454, 455, 456, 457, 458, 459,
    461, 462, 465, 466, 468, 469,
    471, 474, 478, 479,
    480, 481, 482, 483, 484, 485, 486, 488, 489,
    491, 492, 493, 494, 495, 496, 497, 498, 499,
]

# --- Nobina: Järfälla / Upplands-Bro (avtalsområde E43, VR takes over Aug 2026) ---
_NOBINA_JUB = [
    547, 548, 549, 550, 551, 552, 553, 554, 555,
    557, 558, 559, 560, 561, 562, 563, 564, 565, 567, 568, 569,
]

# --- Nobina: Södertälje / Nykvarn (avtalsområde E39, VR takes over Aug 2026) ---
_NOBINA_SN = [
    750, 751, 752, 753, 754, "754X",
    760, 761, 763, 765,
    770, 771, 772, 773, 774, 775, 776, 777, 778, 779,
    780, 781, 783, 784, 786, 789,
]

# --- Nobina: Handen / Nynäshamn (avtalsområde E44, from mid-2025) ---
_NOBINA_HN = [
    801, 802, 803, 804, 805, 806, 807, 808, 809,
    810, 811, 812, 813, 814, 815, 816, 817, 818, 819,
    820, 821, 822, 823, 824, 825, 826, 827, 828, 829,
    830, 831, 832, 833, 834, 835, 836, 837, 838, 839,
    840, 841, 842, 843, 844, 845, 846, 847, 848, 849,
    850, 851, 852, 853, 854, 855, 856, 857, 858, 859,
    860, 861, 862, 863, 865, 869,
]

# --- Transdev: Norrort – Täby/Danderyd/Vaxholm/Österåker/Vallentuna (E35) ---
_TRANSDEV_NORRORT = [
    601, 602, 603, 604, 606, 607, 608, 609,
    610, 611, 612, 613, 614, 615, 616, 617, 618, 619,
    620, 621, 622, 623, 624, 625, 626, 627, 628, 629,
    630, 631, 632, 633, 634, 635, 636, 637, 638, 639,
    640, "640Z", 641, 642, 643, 644, 645, 646, 647, 648, "648Z", 649,
    "669Z",
    670, 671, 672, 673, 674, 675, 680, 681, 682, 683, 688,
]

# --- Transdev: Norrtälje (avtalsområde E38) ---
_TRANSDEV_NORRTALJE = [
    651, 652, 653, 654, 655, 656, 657, 658, 659,
    661, 662, 663, 664, 665, 666, 667, 668,
    676, 677, 678, 679,
    684, 685, 686, 687, 689,
    690, 691, 692, 693, 694, 695, 696, 697, 698, 699,
]

# --- Transdev: Sigtuna / Upplands Väsby / Märsta (avtalsområde E36) ---
_TRANSDEV_SIGTUNA = [
    570, 571, "571X", 572, "573A", "573N", 574, 575, "575X",
    576, 577, 578, 579,
    580, "580E", 581, 582, 583, 584, 589,
    593, 597,
]

# --- VR Sverige: Ekerö (avtalsområde E32) ---
_VR_EKERO = [
    301, 302, 303, 304, 305, 306, 307, 308, 309,
    310, 311, 312, 314, 315, 316, 317, 318,
    336, 338,
]

# --- VR Sverige: Tyresö (avtalsområde E45, from Aug 2025) ---
_VR_TYRESO = [
    871, 872, 873, 874, 875, 876, 877, 878, 879,
    881, 882, 883, 884, 885, 886, 887, 888, 889,
    891, 892, 893, 894, 895, 896, 897, 898, 899,
]

OPERATOR_MAPPING = (
    _expand("Keolis", _KEOLIS_INNERSTAD)
    + _expand("Keolis", _KEOLIS_LIDINGO)
    + _expand("Keolis", _KEOLIS_BROMMA_SOLNA)
    + _expand("Nobina", _NOBINA_HBS)
    + _expand("Nobina", _NOBINA_NV)
    + _expand("Nobina", _NOBINA_JUB)
    + _expand("Nobina", _NOBINA_SN)
    + _expand("Nobina", _NOBINA_HN)
    + _expand("Transdev", _TRANSDEV_NORRORT)
    + _expand("Transdev", _TRANSDEV_NORRTALJE)
    + _expand("Transdev", _TRANSDEV_SIGTUNA)
    + _expand("VR Sverige", _VR_EKERO)
    + _expand("VR Sverige", _VR_TYRESO)
)
