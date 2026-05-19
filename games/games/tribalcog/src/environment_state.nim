type
  TribalErrorKind* = enum
    ## Enumerate environment error categories for diagnostics.
    ErrNone = 0
    ErrMapFull = 1          ## No empty positions are available for placement.
    ErrInvalidPosition = 2  ## A position is out of bounds or invalid.
    ErrResourceNotFound = 3 ## A required resource was not found.
    ErrInvalidState = 4     ## The game reached an invalid state.
    ErrFFIError = 5         ## The FFI layer reported an error.

  TribalError* = object of CatchableError
    ## Represent a tribal village error with structured details.
    kind*: TribalErrorKind
    details*: string

  FFIErrorState* = object
    ## Store thread-local error state for the FFI layer.
    hasError*: bool
    errorCode*: TribalErrorKind
    errorMessage*: string

var
  lastFFIError*: FFIErrorState

proc initFFIErrorState(): FFIErrorState =
  ## Return the default cleared FFI error state.
  FFIErrorState(
    hasError: false,
    errorCode: ErrNone,
    errorMessage: ""
  )

proc clearFFIError*() =
  ## Clear the last FFI error state.
  lastFFIError = initFFIErrorState()

proc newTribalError*(kind: TribalErrorKind, message: string): ref TribalError =
  ## Create a TribalError with the given kind and message.
  result = new(TribalError)
  result.kind = kind
  result.details = message
  result.msg = $kind & ": " & message

proc raiseMapFullError*() {.noreturn.} =
  ## Raise a TribalError when the map has no free placement tile.
  raise newTribalError(
    ErrMapFull,
    "Failed to find an empty position, map too full."
  )
