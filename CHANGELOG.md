# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release planning

## [0.2.0] - 2025-07-05

### Added
- 🗄️ In-memory backend implementation with thread safety
- 🧹 Automatic cleanup of expired entries
- 📏 Memory limit configuration with LRU eviction
- 🔄 Backend factory caching for performance
- 🧪 Comprehensive test suite for memory backend
- 📖 Updated documentation and examples

### Changed
- 🏭 Enhanced backend factory with caching support
- 🔧 Improved decorator key generation logic
- 📋 Updated contributing guidelines
- 🗺️ Marked memory backend as completed in roadmap

### Fixed
- 🔧 Fixed Redis integration test cache clearing
- 🐛 Resolved all pre-commit hook issues (black, flake8, isort, mypy)

## [0.1.1] - 2025-07-05

### Fixed
- 🔧 Fixed PyPI badge display issues in README
- 📦 Updated package classifiers for better PyPI compatibility
- 🏷️ Improved Django version badge display
- 📝 Cleaned up CHANGELOG formatting

### Changed
- 📋 Enhanced README badges with better PyPI integration
- 🎨 Added emoji indicators to CHANGELOG for better readability
- 🔄 Updated supported Django versions to include 5.1

## [0.1.0] - 2025-07-05

### Added
- ✨ Rate limiting decorator with configurable keys and rates
- 🔧 Rate limiting middleware with path-based configuration
- 🔌 Redis backend with sliding window and fixed window algorithms
- 🧪 Comprehensive test suite with >90% coverage
- 📖 Documentation with architecture design and usage examples
- 🚀 CI/CD pipeline with GitHub Actions
- 🔒 Pre-commit hooks for code quality
- 🐍 Support for Python 3.9, 3.10, 3.11, and 3.12
- 🌐 Support for Django 3.2, 4.0, 4.1, 4.2, and 5.0
- 📄 MIT License

### Features
- ⚡ Atomic rate limiting operations using Redis Lua scripts
- 🛣️ Configurable rate limits per path in middleware
- 🔑 Custom key functions for advanced use cases
- 📊 Standard rate limiting headers (X-RateLimit-*)
- 🚫 Blocking and non-blocking rate limiting modes
- 🏥 Health check functionality for Redis backend
- 🛡️ Comprehensive error handling and logging

### Documentation
- 📚 Complete README with usage examples
- 🏗️ Architecture design document
- 📋 API reference documentation
- 🤝 Contributing guidelines
- 📝 Issue and PR templates

[Unreleased]: https://github.com/YasserShkeir/django-smart-ratelimit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/YasserShkeir/django-smart-ratelimit/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/YasserShkeir/django-smart-ratelimit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/YasserShkeir/django-smart-ratelimit/releases/tag/v0.1.0
