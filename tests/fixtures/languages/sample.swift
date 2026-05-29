import Foundation

struct SampleService {
  func add(value: Int) -> Int {
    var total = value
    total += 1
    total += 2
    total += 3
    return total
  }
}

func helper(value: Int) -> Int {
  return value + 1
}
