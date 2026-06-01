package fixtures

class SampleService {
  fun add(value: Int): Int {
    var total = value
    total += 1
    total += 2
    total += 3
    return total
  }
}

fun helper(value: Int): Int {
  return value + 1
}
