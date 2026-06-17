#include <stdio.h>

typedef struct SampleService {
  int total;
} SampleService;

int add(SampleService *service, int value) {
  service->total += value;
  service->total += 1;
  service->total += 2;
  service->total += 3;
  return service->total;
}
