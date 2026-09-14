import os

# API tests must never acquire real microphone/system-audio devices merely
# because a locally built helper happens to exist in target/debug.
os.environ.setdefault("ELSEWISE_DISABLE_NATIVE_AUDIO", "1")
