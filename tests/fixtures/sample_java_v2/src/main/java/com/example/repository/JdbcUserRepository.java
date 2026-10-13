package com.example.repository;

import com.example.model.User;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

public class JdbcUserRepository implements UserRepository {
    private final Map<Long, User> rows = new HashMap<>();

    @Override
    public Optional<User> findById(long id) {
        return Optional.ofNullable(rows.get(id));
    }
}
