'use strict';
const params = require('../parameters.js');

module.exports = (sequelize, DataTypes) => {
  const Experiment = sequelize.define('Experiment', {
    website: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    file: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    email: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    ccas: {
      type: DataTypes.ARRAY(DataTypes.ENUM(params.ccas)),
      allowNull: false,
    },
    status: {
      type: DataTypes.ENUM('Queued', 'In Progress', 'Completed', 'Failed'),
      allowNull: false,
      defaultValue: 'Queued'
    },
    directory: {
      type: DataTypes.STRING,
      allowNull: true,
    }
  }, {});

  Experiment.associate = (models) => {
    Experiment.hasMany(models.Flow, {
      foreignKey: 'experimentId',
      as: 'flows',
    });
  };

  return Experiment;
};