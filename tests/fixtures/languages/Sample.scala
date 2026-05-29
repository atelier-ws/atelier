package fixtures

class SampleService {
  def add(value: Int): Int = {
    var total = value
    total += 1
    total += 2
    total += 3
    total
  }
}

def helper(value: Int): Int = value + 1
