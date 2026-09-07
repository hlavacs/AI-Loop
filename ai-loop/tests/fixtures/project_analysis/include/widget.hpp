#pragma once

#include <string>

class Component {
public:
    virtual std::string name() const = 0;
};

class Widget : public Component {
public:
    Widget();
    std::string name() const override;
};

struct Point {
    double x;
    double y;
};

enum class Mode { idle, active };
using WidgetId = unsigned long;

int add(int left, int right);

#ifdef _WIN32
#include <windows.h>
#elif defined(__linux__)
#include <unistd.h>
#elif defined(__APPLE__)
#include <TargetConditionals.h>
#endif
