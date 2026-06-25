## Tests for envconfig.nim.

import envconfig

suite "Env config":
  test "missing bool values honor the fallback":
    const key = "TV_TEST_BOOL_FALLBACK_MISSING"
    delEnv(key)

    check parseEnvBool(key, true)
    check not parseEnvBool(key, false)

  test "invalid bool values honor the fallback":
    const key = "TV_TEST_BOOL_FALLBACK_INVALID"
    putEnv(key, "maybe")

    check parseEnvBool(key, true)
    check not parseEnvBool(key, false)

    delEnv(key)
