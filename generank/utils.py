def is_in_range(parameter, lower_bound_inclusive, upper_bound_inclusive):
    if parameter < lower_bound_inclusive or parameter > upper_bound_inclusive:
        raise ValueError('Value: %s is not within the tolerance %s...%s.' % (
            parameter, lower_bound_inclusive, upper_bound_inclusive))
    else:
        return parameter


def as_bool(parameter):
    try:
        return int(parameter) == 1
    except ValueError:
        raise ValueError('Value: \'%s\' is not a valid number.' % parameter)
