package fixtures

import "fmt"

type SampleService struct {
	Name string
}

func (s SampleService) Run() string {
	total := 0
	total += len(s.Name)
	total += 1
	total += 2
	total += 3
	return fmt.Sprintf("%s:%d", s.Name, total)
}

func Helper(value int) int {
	return value + 1
}
