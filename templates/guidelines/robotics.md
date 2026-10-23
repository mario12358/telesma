---
tag: robotics
keywords: robot, robotics, hal, hardware, simulator, simulation, sensor, sonar, motor, gpio, i2c, raspberry, safety, behaviours
---

# Guidelines: Robotics

A robot differs from an application in that a bug moves a physical object, and the agent has no access to the
hardware. The only feedback signal is simulation on fake hardware. Everything below follows from that.

## Hardware behind a single layer

- All access to pins, buses (I2C, SPI, UART), audio and display lives in one `hal/` package
- Three files: `base.py` (abstract interfaces, units in the docstrings), `fake.py` (implementation on top of the world model), `real.py` (hardware libraries)
- The implementation is chosen by an environment variable (e.g. `ROBOT_HAL=fake|real`), never by `if`s scattered across the code
- Code outside `hal/` imports nothing hardware-related (`gpiozero`, `lgpio`, `RPi.GPIO`, `smbus2`, `pyaudio`, `picamera2`). Test: a `grep` over imports outside `hal/` comes back empty
- A human writes `real.py`. The agent leaves a skeleton: every method is `raise NotImplementedError("TODO human: <pin/device from the registry>")`. Do not change existing content of `real.py` without a task that explicitly requires it
- The fake implementation **is not a dummy returning zeros**. It simulates the world well enough for the logic to get things wrong: a sensor facing a wall returns a distance, movement changes the pose, a collision sets a flag
- Name interfaces after their function, not the chip model: `Wheels`, `Sonar`, `Battery`, not `PCA9685Driver`, `HCSR04`

## Hardware registry

- Facts about the hardware (pins, addresses, ranges, voltages, dimensions, speeds) live in **one data file** (e.g. `hardware/components.yaml`) outside `telesma/spec/`, because it changes whenever someone resolders something
- Code reads the registry through one loader (e.g. `hardware.py`) with model validation (pydantic): a missing required field is an error at import time, not a `None` at runtime
- **No hardware numbers in the code or in the simulator.** Speed, sonar range, footprint, beam angle come from the registry. If `400` or `0x40` shows up in the code, that is a bug
- A value marked as unverified (e.g. `verify: true`) is true for the code, but do not build anything on it that cannot be changed with a single registry edit
- A component marked as unused (`used: false`) gets no code. Hardware in a drawer is not a requirement
- The pitfalls section of the registry is input for `## Known problems and solutions` in PROJECT_CONTEXT.md: copy it there in the first task
- For every task with this tag: `Read` the hardware registry before implementing. The registry is not in SPEC_INDEX, because it is not part of the frozen spec

## The simulator is the judge, not an add-on

- **One world model** (e.g. `sim/world.py`). Tests, CLI, scenarios and the browser preview use the same class. The preview computes nothing itself and edits nothing
- A 2D world is enough: pose `(x, y, theta)`, a rectangular footprint from the registry, walls as segments, a distance sensor as a ray from the sensor's position, a collision stops the robot and sets a flag
- **Artificial clock.** `World.step(dt)` advances time; never `time.sleep()` or `time.time()` in the simulation. The main loop receives the clock as a parameter, so the same code runs on the artificial and the real one
- Sensor noise is a world parameter (0 by default, so tests are deterministic). Decision latency (e.g. a language model's response time) is a world parameter too — do not leave it out
- Every scenario (`sim/scenarios/*.yaml`) is a separate pytest test via parametrize over the files. The runner returns exit code 0 only when all of them passed, and prints which expectation failed and with what value
- A task that changes the robot's behaviour without a scenario is **unverified**, even when the unit tests are green
- A green simulator means "the logic is consistent with the hardware description", not "it works". A motor wired in reverse, a power brownout, microphone-speaker feedback, encoder drift — the simulator will not catch them. These go into the documentation for humans and into the manual release scenarios (section 15.7), not into tests

## Safety has floors in code

- Safety thresholds (minimum stopping distance, maximum movement time, voltage threshold) have a **minimum written in code** (e.g. `limits.py`) that no rule, configuration or language model can get around. A rule with a value below the limit fails validation at start-up, with a clear message
- These are the only behavioural numbers that live in code. Everything else is data
- **Every movement has a duration.** A drive command without a time limit does not exist in the interface; once the time runs out the wheels stop without any involvement of the higher layer's logic
- **Watchdog.** Loss of the control loop, loss of connection to the decision layer, an exception in a cycle = wheels stop. The motor driver keeps the last PWM after the process dies, so the stop must be explicit and must be the first thing in `finally`
- The stopping distance comes from physics, not intuition: `max_speed × (1/sensor_rate + decision_latency) + braking_distance`. At 40 cm/s and 10 Hz that is 4 cm per sample; a 10 cm threshold is borderline, 20 cm is reasonable. Write the calculation in a comment next to the limit
- Decisions from a language model go through the same limits and the same validation as rules. **The model proposes, the code filters**
- Soft hardware limits from the registry (e.g. `pwm_max_percent`) are enforced by `hal/`, not by logic higher up. Changing a limit requires a human's consent, not a task

## Behaviours are data, not code

- The robot's reactions (condition on a sensor → actions) are data files (e.g. `behaviors/*.yaml`) that the code executes on every cycle. The code provides a vocabulary of conditions and actions; a human composes sentences from it
- A condition is a simple `field operator value` expression, joined by conjunctions. **Do not use `eval`** or `exec`. Write a small parser with an explicit list of fields and operators; an unknown word is a validation error with a hint pointing at the closest known one
- Conflicting actions are resolved by explicit priority. Safety rules have the highest one and live in a separate file
- Every rule that fires logs: its name, the condition values, the actions performed. That is the data for the "why" panel and for scenarios (`expect: rule_fired`)
- When a task needs a code change instead of a data change, a word is missing from the vocabulary. Add the word, describe it in the human-facing vocabulary documentation, and only then write the rule. Never hardcode behaviour "because it is faster"
- Update the human-facing vocabulary (e.g. `docs/RULES.md`) in the same task in which you add a word. Without it the word does not exist for a rule author who does not read the code
- Canonical word names in English in the engine; aliases in the user's language in a separate mapping file, if the project needs them. The parser normalises before validating

## Process

- **The agent never uploads code to the robot.** A human runs the deployment script; no test, `Makefile`, CI or helper script calls it. Test: a `grep` over `.github/` and `Makefile` does not find the deployment script's name
- The deployment script has `--dry-run` and asks for confirmation before restarting the service on the robot
- A new dependency only from a task that names it. Needing anything more is `TELESMA BLOCKED`, not `pip install`
- The code runs on macOS, Windows and Linux, because people program the robot from their laptops. Helper scripts in Python, not in bash. CI on all three systems
- Identifiers in code in English. The language of human-facing documentation, validation messages and comments is set by the project
- Secrets (API keys, robot passwords) in `.env`, template in `.env.example`. The robot's address is configuration too, not a literal

## Platform (Raspberry Pi and similar)

- Separate power for the computer and for the motors. Shared power resets the computer when the motors start. Record this in the registry and in the assembly instructions
- The first power-up goes from least to most risky: HATs without motor power (`i2cdetect` shows all addresses) → power without motors → one pair of wheels → the rest. Check the direction of each wheel separately, because motors are sometimes mounted rotated by 180°
- Logic voltages: a 5 V sensor without a voltage divider will damage a 3.3 V GPIO. The chip variant (e.g. HC-SR04 versus HC-SR04P) is a field in the registry, not knowledge in someone's head
- Audio devices by ALSA names from the configuration, not card numbers (they change after a reboot). Do not force a sample rate the device does not support; detect the native one and resample
- GPIO through `gpiozero` (with the `lgpio` backend) — `RPi.GPIO` does not work on Raspberry Pi 5 and recent kernels; I2C through `smbus2`; the camera through `picamera2`
- Hardware libraries from system packages: a venv with `--system-site-packages`, and `real.py` imports them lazily, so that `fake` works on a laptop without them
- The robot runs as a `systemd --user` service with restart; logs via `journalctl`. System preparation instructions for humans in `deploy/`

## What to avoid

- Hardware imports outside `hal/`
- Hardware numbers in the code and the simulator
- `time.sleep()` in control logic and in the simulation
- `eval` in the rule parser
- Behaviours baked into code instead of data
- Movement commands without a time limit
- Hardware mocks in tests instead of a fake HAL on top of the world model (a mock does not let the logic get things wrong)
- Triggering deployment from anything other than a human's hand
- Code for hardware marked as unused
- Changes to `real.py` and to the safety floors without an explicitly named task
