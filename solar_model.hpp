#pragma once
// Shared by the original C++ CLI, the Python server and the offline web map.
#include <algorithm>
#include <cmath>

namespace ncu_solar {
constexpr double latitudeNorth = 24.96828;
constexpr double longitudeEast = 121.195474;
struct Angles { double azimuth, elevation; };

inline double wrapPositive(double value, double period)
{
    const double remainder = std::fmod(value, period);
    return remainder < 0.0 ? remainder + period : remainder + 0.0;
}

inline double radians(double degrees)
{
    return degrees * 3.14159265358979323846 / 180.0;
}

inline double degrees(double radians)
{
    return radians * 180.0 / 3.14159265358979323846;
}

inline Angles calculate(double unixSeconds)
{
    // NOAA GML's Meeus-based Solar Calculator equations. Use geometric elevation.
    const double julianDay = 2440587.5 + unixSeconds / 86400.0;
    const double t = (julianDay - 2451545.0) / 36525.0;
    const double meanLongitude = wrapPositive(280.46646 + t * (36000.76983 + 0.0003032 * t), 360.0);
    const double anomaly = radians(357.52911 + t * (35999.05029 - 0.0001537 * t));
    const double eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
    const double center = std::sin(anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
                        + std::sin(2.0 * anomaly) * (0.019993 - 0.000101 * t)
                        + std::sin(3.0 * anomaly) * 0.000289;
    const double omega = radians(125.04 - 1934.136 * t);
    const double apparentLongitude = radians(meanLongitude + center - 0.00569 - 0.00478 * std::sin(omega));
    const double obliquitySeconds = 21.448 - t * (46.8150 + t * (0.00059 - t * 0.001813));
    const double obliquity = radians(23.0 + 26.0 / 60.0 + obliquitySeconds / 3600.0
                                    + 0.00256 * std::cos(omega));
    const double declination = std::asin(std::sin(obliquity) * std::sin(apparentLongitude));

    const double longitude = radians(meanLongitude);
    const double halfObliquityTangent = std::tan(obliquity / 2.0);
    const double y = halfObliquityTangent * halfObliquityTangent;
    const double equationOfTime = 4.0 * degrees(
        y * std::sin(2.0 * longitude) - 2.0 * eccentricity * std::sin(anomaly)
        + 4.0 * eccentricity * y * std::sin(anomaly) * std::cos(2.0 * longitude)
        - 0.5 * y * y * std::sin(4.0 * longitude)
        - 1.25 * eccentricity * eccentricity * std::sin(2.0 * anomaly));
    const double utcMinutes = wrapPositive(unixSeconds, 86400.0) / 60.0;
    const double solarMinutes = wrapPositive(utcMinutes + equationOfTime + 4.0 * longitudeEast, 1440.0);
    const double hourAngle = radians(solarMinutes / 4.0 - 180.0);
    const double latitude = radians(latitudeNorth);

    // Components of the Sun's unit direction in the local east-north-up frame.
    const double east = -std::cos(declination) * std::sin(hourAngle);
    const double north = std::sin(declination) * std::cos(latitude)
                       - std::cos(declination) * std::sin(latitude) * std::cos(hourAngle);
    const double up = std::sin(declination) * std::sin(latitude)
                    + std::cos(declination) * std::cos(latitude) * std::cos(hourAngle);
    return {wrapPositive(degrees(std::atan2(east, north)), 360.0),
            degrees(std::asin(std::clamp(up, -1.0, 1.0)))};
}
} // namespace ncu_solar
