package com.example.service;

import com.example.model.User;
import com.example.repository.JdbcUserRepository;
import com.example.repository.UserRepository;

public class UserService<T> {
    private final UserRepository repository;

    public UserService() {
        this.repository = new JdbcUserRepository();
    }

    public User getUser(long id, T context) {
        var result = repository.findById(id);
        return result.orElse(null);
    }

    static class Cache {
        private User last;
    }
}
