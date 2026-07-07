#include <string>

namespace fixtures {
class SampleService {
 public:
  int add(int value) {
    int total = value;
    total += 1;
    total += 2;
    total += 3;
    return total;
  }
};
}
