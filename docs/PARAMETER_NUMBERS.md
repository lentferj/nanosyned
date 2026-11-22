# Parameter numbers

Rows are transcribed from the published QS6/7/8/R specification. A row is writable only once a controlled before/after probe confirms its offset and value law.

The map holds 178 rows across 4 modes; 75 of them are verified.

## Summary

| mode | rows | verified |
| --- | --- | --- |
| global | 20 | 10 |
| mix | 33 | 27 |
| effects | 81 | 0 |
| program | 44 | 38 |

## global

| function | page | pot | label | bits | bit address | range | offset | law | verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -1 | -1 | -1 | Clock *(QS7,8,R only) | 1 | 120 | 0..1 | 0 | (inferred) | no |
| -1 | -1 | -1 | Global spare (deleted parameter) 0:6-0:0 | 7 | 0 | 0..0 | 0 | (inferred) | no |
| -1 | -1 | -1 | Global spare (deleted parameter) 14:6-14:0 | 7 | 112 | 0..0 | 0 | (inferred) | no |
| 0 | 0 | 1 | General MIDI | 1 | 136 | 0..1 | 0 | (inferred) | no |
| 0 | 0 | 2 | Pitch transpose* | 8 | 8 | -12..12 | 0 | twos | yes |
| 0 | 0 | 3 | Pitch fine tune* | 8 | 16 | -99..99 | 0 | twos | yes |
| 0 | 1 | 0 | Keyboard scaling | 7 | 24 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 1 | Keyboard curve *(QS6,7,8 only) | 2 | 32 | 0..2 | 0 | (inferred) | no |
| 0 | 1 | 2 | Keyboard Transpose | 8 | 40 | -12..12 | 0 | (inferred) | no |
| 0 | 1 | 3 | Keyboard mode *(QS6,7,8 only) | 5 | 48 | 0..17 | 0 | (inferred) | no |
| 0 | 2 | 0 | Controller A number | 7 | 56 | 0..120 | 0 | twos | yes |
| 0 | 2 | 1 | Controller B number | 7 | 64 | 0..120 | 0 | twos | yes |
| 0 | 2 | 2 | Controller C number | 7 | 72 | 0..120 | 0 | twos | yes |
| 0 | 2 | 3 | Controller D number | 7 | 80 | 0..120 | 0 | twos | yes |
| 0 | 3 | 1 | A-D controller reset | 1 | 144 | 0..1 | 0 | twos | yes |
| 0 | 3 | 3 | A-D controller mode | 2 | 152 | 0..2 | 0 | (inferred) | no |
| 0 | 4 | 0 | Pedal 1 controller number | 7 | 88 | 0..120 | 0 | twos | yes |
| 0 | 4 | 2 | Pedal 2 controller number | 7 | 96 | 0..120 | 0 | twos | yes |
| 0 | 5 | 0 | MIDI program select | 5 | 104 | 0..17 | 0 | twos | yes |
| 0 | 6 | 0 | Mix Group Channel *(QSR only) | 5 | 128 | 0..16 | 0 | (inferred) | no |

## mix

| function | page | pot | label | bits | bit address | range | offset | law | verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -1 | -1 | -1 | Channel 1 Spare | 1 | 143 | 0..0 | 0 | (inferred) | no |
| -1 | -1 | -1 | Mix spare | 5 | 75 | 0..0 | 0 | (inferred) | no |
| 0 | 0 | 0 | Channel 1 program number | 7 | 80 | 0..127 | 0 | (inferred) | no |
| 0 | 0 | 2 | Channel 1 program type | 4 | 87 | 0..15 | 0 | (inferred) | no |
| 0 | 0 | 3 | Channel 1 enable | 1 | 91 | 0..1 | 0 | raw | yes |
| 1 | 0 | 0 | Channel 1 volume | 7 | 92 | 0..99 | 0 | raw | yes |
| 1 | 0 | 1 | Channel 1 pan | 3 | 99 | 0..7 | 0 | raw | yes |
| 1 | 0 | 2 | Channel 1 output | 2 | 102 | 0..3 | 0 | raw | yes |
| 2 | 0 | 0 | Channel 1 effect level | 7 | 104 | 0..100 | 0 | raw | yes |
| 2 | 0 | 1 | Channel 1 effect bus | 3 | 111 | 0..4 | 0 | raw | yes |
| 3 | 0 | 0 | Channel 1 pitch octave | 3 | 114 | -2..3 | -2 | (inferred) | no |
| 3 | 0 | 2 | Channel 1 pitch semitone | 5 | 117 | -12..12 | -12 | offset | yes |
| 4 | 0 | 0 | Channel 1 keyboard low note | 7 | 122 | 0..127 | 0 | raw | yes |
| 4 | 0 | 1 | Channel 1 keyboard high note | 7 | 129 | 0..127 | 0 | raw | yes |
| 4 | 1 | 0 | Channel 1 midi in on/off | 1 | 136 | 0..1 | 0 | raw | yes |
| 4 | 1 | 2 | Channel 1 midi out on/off | 1 | 137 | 0..1 | 0 | raw | yes |
| 4 | 1 | 3 | Channel 1 keyboard on/off ** | 1 | 138 | 0..1 | 0 | raw | yes |
| 4 | 2 | 0 | Channel 1 wheels on/off | 1 | 139 | 0..1 | 0 | raw | yes |
| 4 | 2 | 1 | Channel 1 Aftertouch on/off | 1 | 140 | 0..1 | 0 | raw | yes |
| 4 | 2 | 2 | Channel 1 Sustain pedal on/off | 1 | 141 | 0..1 | 0 | raw | yes |
| 4 | 2 | 3 | Channel 1 Pedals/controllers on/off | 1 | 142 | 0..1 | 0 | raw | yes |
| 5 | 0 | 2 | Mix effect MIDI program change | 1 | 0 | 0..1 | 0 | (inferred) | no |
| 5 | 0 | 3 | Mix effect chan | 4 | 1 | 0..15 | 0 | raw | yes |
| 6 | 0 | 0 | Mix name digit 0 | 7 | 5 | 0..95 | 0 | raw | yes |
| 6 | 1 | 0 | Mix name digit 1 | 7 | 12 | 0..95 | 0 | raw | yes |
| 6 | 2 | 0 | Mix name digit 2 | 7 | 19 | 0..95 | 0 | raw | yes |
| 6 | 3 | 0 | Mix name digit 3 | 7 | 26 | 0..95 | 0 | raw | yes |
| 6 | 4 | 0 | Mix name digit 4 | 7 | 33 | 0..95 | 0 | raw | yes |
| 6 | 5 | 0 | Mix name digit 5 | 7 | 40 | 0..95 | 0 | raw | yes |
| 6 | 6 | 0 | Mix name digit 6 | 7 | 47 | 0..95 | 0 | raw | yes |
| 6 | 7 | 0 | Mix name digit 7 | 7 | 54 | 0..95 | 0 | raw | yes |
| 6 | 8 | 0 | Mix name digit 8 | 7 | 61 | 0..95 | 0 | raw | yes |
| 6 | 9 | 0 | Mix name digit 9 | 7 | 68 | 0..95 | 0 | raw | yes |

## effects

| function | page | pot | label | bits | bit address | range | offset | law | verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 0 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 7 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 14 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 21 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 28 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 35 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 42 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 49 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 56 | 0..95 | 0 | (inferred) | no |
| -1 | -1 | -1 | Effect spare (deleted parameter) | 7 | 63 | 0..95 | 0 | (inferred) | no |
| 0 | 0 | 0 | Send 1 pitch type | 3 | 74 | 0..5 | 0 | (inferred) | no |
| 0 | 0 | 0 | Send 2 pitch type | 3 | 246 | 0..5 | 0 | (inferred) | no |
| 0 | 0 | 0 | Send 3 pitch type | 2 | 348 | 0..2 | 0 | (inferred) | no |
| 0 | 1 | 0 | Send 1 pitch shape | 1 | 84 | 0..1 | 0 | (inferred) | no |
| 0 | 1 | 0 | Send 2 pitch shape | 1 | 256 | 0..1 | 0 | (inferred) | no |
| 0 | 1 | 0 | Send 3 pitch shape | 1 | 357 | 0..1 | 0 | (inferred) | no |
| 0 | 1 | 1 | Send 1 pitch speed | 7 | 77 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 1 | Send 2 pitch speed | 7 | 249 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 1 | Send 3 pitch speed | 7 | 350 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 2 | Send 1 pitch depth | 7 | 85 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 2 | Send 2 pitch depth | 7 | 257 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 2 | Send 3 pitch depth | 7 | 358 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 3 | Send 1 pitch feedback | 7 | 92 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 3 | Send 2 pitch feedback | 7 | 264 | 0..99 | 0 | (inferred) | no |
| 0 | 1 | 3 | Send 3 pitch feedback | 7 | 365 | 0..99 | 0 | (inferred) | no |
| 1 | 0 | 0 | MIDImod source 1 | 4 | 470 | 0..10 | 0 | (inferred) | no |
| 1 | 0 | 1 | MIDImod destination 1 | 6 | 474 | 0..36 | 0 | (inferred) | no |
| 1 | 0 | 2 | MIDImod level 1 | 8 | 480 | -99..99 | -99 | (inferred) | no |
| 1 | 1 | 0 | MIDImod source 2 | 4 | 488 | 0..10 | 0 | (inferred) | no |
| 1 | 1 | 1 | MIDImod destination 2 | 6 | 492 | 0..36 | 0 | (inferred) | no |
| 1 | 1 | 2 | MIDImod level 2 | 8 | 498 | -99..99 | -99 | (inferred) | no |
| 2 | 0 | 0 | Effect configuration | 4 | 70 | 0..4 | 0 | (inferred) | no |
| 3 | 0 | 0 | Send 1 reverb input 1 | 1 | 162 | 0..1 | 0 | (inferred) | no |
| 3 | 0 | 0 | Send 2 reverb input 1 | 1 | 330 | 0..1 | 0 | (inferred) | no |
| 3 | 0 | 0 | Send 3 reverb input 1 | 1 | 412 | 0..1 | 0 | (inferred) | no |
| 3 | 0 | 0 | Send 4 reverb balance | 8 | 455 | -99..99 | -99 | (inferred) | no |
| 3 | 0 | 1 | Send 1 reverb input 2 | 2 | 163 | 0..2 | 0 | (inferred) | no |
| 3 | 0 | 1 | Send 2 reverb input 2 | 2 | 331 | 0..2 | 0 | (inferred) | no |
| 3 | 0 | 1 | Send 3 reverb input 2 | 2 | 413 | 0..2 | 0 | (inferred) | no |
| 3 | 0 | 2 | Send 1 reverb balance | 8 | 165 | -99..99 | -99 | (inferred) | no |
| 3 | 0 | 2 | Send 2 reverb balance | 8 | 333 | -99..99 | -99 | (inferred) | no |
| 3 | 0 | 2 | Send 3 reverb balance | 8 | 415 | -99..99 | -99 | (inferred) | no |
| 3 | 0 | 2 | Send 4 reverb input level | 7 | 463 | 0..99 | 0 | (inferred) | no |
| 3 | 0 | 3 | Send 1 reverb input level | 7 | 173 | 0..99 | 0 | (inferred) | no |
| 3 | 0 | 3 | Send 2 reverb input level | 7 | 341 | 0..99 | 0 | (inferred) | no |
| 3 | 0 | 3 | Send 3 reverb input level | 7 | 423 | 0..99 | 0 | (inferred) | no |
| 3 | 1 | 0 | Reverb type | 4 | 158 | 0..6 | 0 | (inferred) | no |
| 3 | 1 | 1 | Send 1 reverb prdly 10ms | 5 | 180 | 0..29 | 0 | (inferred) | no |
| 3 | 1 | 2 | Send 1 reverb prdly 1ms | 4 | 185 | 0..9 | 0 | (inferred) | no |
| 3 | 1 | 3 | Send 1 reverb inut premix | 8 | 189 | -99..99 | -99 | (inferred) | no |
| 3 | 2 | 0 | Send 1 reverb input filter | 7 | 197 | 0..99 | 0 | (inferred) | no |
| 3 | 2 | 1 | Send 1 reverb decay | 7 | 204 | 0..99 | 0 | (inferred) | no |
| 3 | 2 | 2 | Send 1 reverb low decay | 7 | 225 | 0..99 | 0 | (inferred) | no |
| 3 | 2 | 3 | Send 1 reverb high decay | 7 | 232 | 0..99 | 0 | (inferred) | no |
| 3 | 3 | 0 | Send 1 reverb density | 7 | 218 | 0..99 | 0 | (inferred) | no |
| 3 | 3 | 2 | Send 1 reverb diffusion | 7 | 211 | 0..99 | 0 | (inferred) | no |
| 4 | 0 | 0 | Send 1 delay type | 2 | 106 | 0..2 | 0 | (inferred) | no |
| 4 | 0 | 0 | Send 2 delay type | 2 | 278 | 0..2 | 0 | (inferred) | no |
| 4 | 0 | 0 | Send 3 delay input | 8 | 379 | -99..99 | -99 | (inferred) | no |
| 4 | 0 | 1 | Send 3 delay 10ms | 7 | 387 | 0..79 | 0 | (inferred) | no |
| 4 | 0 | 1 | Send 4 delay 10ms | 7 | 430 | 0..79 | 0 | (inferred) | no |
| 4 | 0 | 2 | Send 3 delay 1ms | 4 | 394 | 0..9 | 0 | (inferred) | no |
| 4 | 0 | 2 | Send 4 delay 1ms | 4 | 437 | 0..9 | 0 | (inferred) | no |
| 4 | 0 | 3 | Send 3 delay feedback | 7 | 398 | 0..99 | 0 | (inferred) | no |
| 4 | 0 | 3 | Send 4 delay feedback | 7 | 441 | 0..99 | 0 | (inferred) | no |
| 4 | 1 | 0 | Send 1 delay input | 8 | 108 | -99..99 | -99 | (inferred) | no |
| 4 | 1 | 0 | Send 2 delay input | 8 | 280 | -99..99 | -99 | (inferred) | no |
| 4 | 1 | 1 | Send 1 delay 10ms | 7 | 116 | 0..79 | 0 | (inferred) | no |
| 4 | 1 | 1 | Send 2 delay 10ms | 7 | 288 | 0..79 | 0 | (inferred) | no |
| 4 | 1 | 2 | Send 1 delay 1ms | 4 | 123 | 0..9 | 0 | (inferred) | no |
| 4 | 1 | 2 | Send 2 delay 1ms | 4 | 295 | 0..9 | 0 | (inferred) | no |
| 4 | 1 | 3 | Send 1 delay feedback | 7 | 137 | 0..99 | 0 | (inferred) | no |
| 4 | 1 | 3 | Send 2 delay feedback | 7 | 309 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 0 | Send 1 pitch mix | 7 | 99 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 0 | Send 2 pitch mix | 7 | 271 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 0 | Send 3 pitch mix | 7 | 372 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 0 | Send 4 delay mix | 7 | 448 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 1 | Send 1 delay mix | 7 | 151 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 1 | Send 2 delay mix | 7 | 323 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 1 | Send 3 delay mix | 7 | 405 | 0..99 | 0 | (inferred) | no |
| 5 | 0 | 2 | Send 1 reverb mix | 7 | 239 | 0..99 | 0 | (inferred) | no |

## program

| function | page | pot | label | bits | bit address | range | offset | law | verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -1 | -1 | -1 | Program spare (deleted parameter) | 7 | 0 | 0..0 | 0 | (inferred) | no |
| -1 | -1 | -1 | Program spare (deleted parameter) | 1 | 7 | 0..0 | 0 | (inferred) | no |
| -1 | -1 | -1 | ROM Identifier | 2 | 78 | 0..3 | 0 | (inferred) | no |
| 0 | 0 | 0 | Sample group | 6 | 1 | 0..47 | 0 | (inferred) | no |
| 0 | 0 | 2 | Sample number | 7 | 7 | 0..127 | 0 | (inferred) | no |
| 1 | 0 | 0 | Sound volume | 7 | 14 | 0..99 | 0 | raw | yes |
| 1 | 0 | 1 | Sound pan | 3 | 21 | 0..6 | 0 | raw | yes |
| 1 | 0 | 2 | Sound output | 2 | 24 | 0..2 | 0 | raw | yes |
| 2 | 0 | 0 | Sound effect level | 7 | 26 | 0..99 | 0 | raw | yes |
| 2 | 0 | 1 | Sound effect bus | 2 | 33 | 0..3 | 0 | raw | yes |
| 3 | 0 | 0 | Sound pitch semitone | 6 | 35 | -24..24 | -24 | offset | yes |
| 3 | 0 | 2 | Sound pitch detune | 8 | 41 | -99..99 | -99 | offset | yes |
| 3 | 0 | 3 | Sound pitch detune type | 1 | 49 | 0..1 | 0 | raw | yes |
| 3 | 1 | 0 | Sound pitch wheel mod | 4 | 50 | 0..12 | 0 | raw | yes |
| 3 | 1 | 1 | Sound pitch aftertouch mod | 8 | 54 | -99..99 | -99 | offset | yes |
| 3 | 1 | 2 | Sound pitch lfo mod | 8 | 62 | -99..99 | -99 | offset | yes |
| 3 | 1 | 3 | Sound pitch env mod | 8 | 70 | -99..99 | -99 | offset | yes |
| 3 | 2 | 0 | Sound portamento mode | 2 | 78 | 0..2 | 0 | raw | yes |
| 3 | 2 | 2 | Sound portamento rate | 7 | 80 | 0..99 | 0 | raw | yes |
| 3 | 2 | 3 | Sound key mode | 2 | 87 | 0..2 | 0 | raw | yes |
| 4 | 0 | 0 | Sound filter frequency | 7 | 89 | 0..99 | 0 | raw | yes |
| 4 | 0 | 1 | Sound filter keyboard track | 1 | 96 | 0..1 | 0 | raw | yes |
| 4 | 0 | 3 | Sound filter velocity mod | 8 | 97 | -99..99 | -99 | offset | yes |
| 4 | 1 | 0 | Sound filter pitch wheel mod | 8 | 105 | -99..99 | -99 | offset | yes |
| 4 | 1 | 1 | Sound filter aftertouch mod | 8 | 113 | -99..99 | -99 | offset | yes |
| 4 | 1 | 2 | Sound filter lfo mod | 8 | 121 | -99..99 | -99 | offset | yes |
| 4 | 1 | 3 | Sound filter env mod | 8 | 129 | -99..99 | -99 | offset | yes |
| 5 | 0 | 0 | Sound amp velocity curve | 4 | 137 | 0..12 | 0 | raw | yes |
| 5 | 0 | 1 | Sound amp aftertouch mod | 8 | 141 | -99..99 | -99 | offset | yes |
| 5 | 0 | 2 | Sound amp alfo mod | 8 | 149 | -99..99 | -99 | offset | yes |
| 6 | 0 | 0 | Sound low note limit | 7 | 157 | 0..127 | 0 | raw | yes |
| 6 | 0 | 1 | Sound high note limit | 7 | 164 | 0..127 | 0 | raw | yes |
| 6 | 0 | 2 | Sound overlap | 7 | 171 | 0..99 | 0 | raw | yes |
| 8 | 0 | 0 | Program name digit 0 | 7 | 8 | 0..95 | 0 | raw | yes |
| 8 | 1 | 0 | Program name digit 1 | 7 | 15 | 0..95 | 0 | raw | yes |
| 8 | 2 | 0 | Program name digit 2 | 7 | 22 | 0..95 | 0 | raw | yes |
| 8 | 3 | 0 | Program name digit 3 | 7 | 29 | 0..95 | 0 | raw | yes |
| 8 | 4 | 0 | Program name digit 4 | 7 | 36 | 0..95 | 0 | raw | yes |
| 8 | 5 | 0 | Program name digit 5 | 7 | 43 | 0..95 | 0 | raw | yes |
| 8 | 6 | 0 | Program name digit 6 | 7 | 50 | 0..95 | 0 | raw | yes |
| 8 | 7 | 0 | Program name digit 7 | 7 | 57 | 0..95 | 0 | raw | yes |
| 8 | 8 | 0 | Program name digit 8 | 7 | 64 | 0..95 | 0 | raw | yes |
| 8 | 9 | 0 | Program name digit 9 | 7 | 71 | 0..95 | 0 | raw | yes |
| 16 | 0 | 0 | Keyboard / drum mode (=0) | 1 | 0 | 0..1 | 0 | (inferred) | no |
